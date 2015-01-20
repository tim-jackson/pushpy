"""apns.py: Module which contains functionality enabling push notification
messages to be sent to the APNS. """

import time
import common
import base64
import struct
import datetime
import collections
import Queue
import binascii
from twisted.internet.protocol import Protocol, ReconnectingClientFactory
from twisted.python import log
from twisted.internet import error, reactor

APNS_HOSTNAME = "gateway.push.apple.com"
APNS_SANDBOX_HOSTNAME = "gateway.sandbox.push.apple.com"
APNS_PORT = 2195
APNS_RECONNECT_FREQUENCY = 1800
FORMAT_STRING = "!ciLH32sH%ds"
COMMAND_TYPE = "\x01"
MAX_MESSAGE_SIZE_BYTES = 256
MESSAGE_RETRY_COUNT = 0
TIMEOUT_CHECK_FREQUENCY = 900
MIN_MESSAGE_ID = 1000
MAX_MESSAGE_ID = 2147483647

# Indexes relating to error tuples received as a response from the APNS
ERROR_VALUE_INDEX = 0
SENT_MESSAGE_INDEX = 1

class APNSException(Exception):
    """ Class representing an Exception which is used to report issues
        when connecting to or sending messages to the APNS. """

    def __init__(self, error_message):
        self.error_text = error_message
        super(APNSException, self).__init__(self.error_text)

class APNSProtocol(Protocol):
    """ Protocol class which handles connection events made to and
        received from the APNS. """

    def __init__(self):
        self.connect_time = None
        self.alerted = False
        self.last_message_sent = datetime.datetime.now()

        # Set the timeout check value to force reconnection, if a message
        # has not been sent within a certain time interval
        self.set_timeout_trigger()

    def set_timeout_trigger(self):
        """ Sets the trigger to call the reconnect function after a certain
            period of time, to kick of a reconnection to the APNS if
            necessary. """

        self.reconnect_trigger = reactor.callLater(TIMEOUT_CHECK_FREQUENCY,
                                                  self.reconnect)

    def reconnect(self):
        """ Forces the connection to the APNS to be lost. Will then trigger
            a reconnection. """

        log.msg("Running APNS timeout check")
        reconnect_trigger = datetime.datetime.now() - \
            datetime.timedelta(0, APNS_RECONNECT_FREQUENCY)

        if self.last_message_sent <= reconnect_trigger:
            # Remove the last message that was sent - as we are forcefully
            # reconnecting it will be old enough to be removed
            log.msg("Forcing a reconnection to the APNS")
            self.factory.message = None
            self.transport.abortConnection()
            self.set_timeout_trigger()
        else:
            self.set_timeout_trigger()

    def connectionMade(self):
        """ Called when a connection has been established, and acts as a
            trigger to start processing any messages that have been received but
            have not yet been sent. """

        self.connect_time = datetime.datetime.now()

        # Update the time that the last message was 'sent' - i.e. reset
        # the timeout
        self.last_message_sent = datetime.datetime.now()

        if self.factory.message_error is not None:
            self.factory.process_failed_sent_messages()

        if hasattr(self, 'message'):
            if self.factory.retry_attempts < MESSAGE_RETRY_COUNT:
                self.transport.write(self.message)
                del self.message
            else:
                # Already tried to send the message the maximum number of
                # times, so delete and reset the retry count
                del self.message
                self.factory.retry_attempts = 0
        else:
            pass

        self.factory.process_queue()

    def connectionLost(self, reason):
        """ Raise the retry attempts by 1, to prevent continuously
            trying to send the same message if it is erroring. """

        if (datetime.datetime.now() - self.connect_time).seconds <= 1:
            if self.alerted is False:
                log.err("Detected immediate disconnect. Alert")
                self.alerted = True
            else:
                log.err("Immediate disconnect detected. Already alerted")
        else:
            if self.alerted is True:
                log.msg("APNS Connectivity issue resolved")
                self.alerted = False

        self.factory.retry_attempts += 1
        log.msg("APNS Connection lost")

    def dataReceived(self, data):
        """ No data is received when messages are sent successfully - a
            response is only received when something has gone wrong. """

        error_tuple = struct.unpack("!bbi", data)

        log.msg("Error code {0} received when sending message id {1}".format(
            error_tuple[1], error_tuple[2]))

        try:
            if int(error_tuple[2]) == 0:
                log.msg("Error response contained a message id of 0. Resend " \
                        "process not being invoked.")
            else:
                self.factory.message_error = int(error_tuple[2])
                self.factory.error_callback((error_tuple[1], error_tuple[2]))
        except ValueError:
            log.err("Could not parse the message id from the response: {0}".
                    format(error_tuple))

    def sendMessage(self, message):
        """ Sends the fully formed message to the APNS. """

        self.transport.write(message)
        self.last_message_sent = datetime.datetime.now()

    def shutdown(self):
        """ Cancels the deferred task to periodically reconnect to the APNS. """

        self.reconnect_trigger.cancel()

class APNSClientFactory(ReconnectingClientFactory):
    """ Factory which manages instances of the protocol which connect to the
        APNS to dispatch messages to clients. """

    def __init__(self, error_callback, backlog_queue_size=1):
        log.msg("init called")
        self._connected = False
        self.message = None
        self.error_callback = error_callback
        self.message_queue = Queue.Queue(maxsize=backlog_queue_size)
        self.protocol = APNSProtocol()
        self.retry_attempts = 0
        self.sent_messages = collections.deque(maxlen=1000)
        self.sequence_number = MIN_MESSAGE_ID
        self.message_error = None

    def process_queue(self):
        """ Processes the messages in the backlog queue, if there
            are any that have not already been sent. Messages would be
            in the queue if they have been consumed from the MQ but no
            connection to the APNS was available. """

        log.msg(("Processing the backlog of APNS messages."))

        # According to the documentation, Queue.qsize() technically only
        # returns an 'approximate' size - so it's possible that a few messages
        # may get missed or it will try and process more messages than there
        # are available.
        for _ in range(0, self.message_queue.qsize()):
            try:
                message = self.message_queue.get(block=False)
                self.sendMessage(message[0], message[1])
            except Queue.Empty:
                break

        log.msg(("Finished processing the APNS message backlog."))

    def buildProtocol(self, addr):
        """ Builds an instance of the APNSProtocol which is used to
            connect to the APNS. """

        log.msg("Building a new APNS protocol")
        new_protocol = self.protocol

        # Reset the delay between connection attempts, and let the protocol
        # know about this factory
        self.resetDelay()
        new_protocol.factory = self

        log.msg(("Connected to the APNS at {0}:{1}").format(
            addr.host, addr.port))

        # Restart processing incoming messages
        self._connected = True

        return new_protocol

    def startedConnecting(self, connector):
        """ Called when a connection attempt to the APNS has started. """

        log.msg("Attempting to connect to the APNS.")

    def enque_message(self, device_token, payload):
        """ Adds a payload with the corresponding device token
            to the queue. Used when a connection to the APNS is unavailable
            but where it is useful to have the option to send messages
            upon reconnection. """

        if not self.message_queue.full():
            try:
                self.message_queue.put((device_token, payload),
                                        block=False)
                log.msg(("Message for device {0} stored in " +
                         "queue as no APNS connection is available").format(
                         device_token))
            except Queue.Full:
                log.msg(("No connection to the APNS is available, and " +
                         "the queue is full. Discarding message."))
        else:
            try:
                # Pop the first item off to make space for the newer message
                self.message_queue.get(block=False)
                self.message_queue.put((device_token, payload),
                                        block=False)
                log.msg(("Full Queue - message popped to make way for newer " +
                         "message for device {0}, as no " +
                         "APNS connection is available").format(
                         device_token))
            except Queue.Full:
                log.msg("No connection to the APNS is available, and the " +
                        "queue is full. Discarding message.")
            except Queue.Empty:
                log.msg("No connection to the APNS is available, and " +
                        "unable to store message in queue. Discarding " +
                        "message.")

    def sendMessage(self, device_token, payload):
        """ Notification messages are binary messages in network order
        using the following format:
        <1 byte command> <2 bytes length><token> <2 bytes length><payload> """

        try:
            decoded_token = base64.decodestring(device_token)
            message_format = FORMAT_STRING % len(payload)
        except binascii.Error:
            raise APNSException("Unable to decode APNS device token {0}. " \
                    "Discarding message".format(device_token))

        expiry = int(time.time()) + 3600

        try:
            self.message = struct.pack(message_format, COMMAND_TYPE,
                                        int(self.sequence_number), expiry,
                                        len(decoded_token), decoded_token,
                                        len(payload), payload)
        except struct.error:
            raise APNSException("Unable to pack message with payload {0} to " \
                                "send to device {1}. Discarding " \
                                "message".format(payload, device_token))

        if self._connected is True:
            if len(self.message) <= MAX_MESSAGE_SIZE_BYTES:
                self.sent_messages.append({self.sequence_number :
                    [device_token, self.message]})
                self.protocol.sendMessage(self.message)
                if self.sequence_number >= MAX_MESSAGE_ID:
                    self.sequence_number = MIN_MESSAGE_ID
                else:
                    self.sequence_number = self.sequence_number + 1
            else:
                raise APNSException("The message size ({0}) exceeds the " \
                                    "maximum permitted by the APNS ({1}). " \
                                    "Discarding message".format(
                                    str(len(self.message)),
                                    str(MAX_MESSAGE_SIZE_BYTES)))

            log.msg(("Message pushed to device with " \
                     "APNS token: {1}").format(device_token))
        else:
            self.enque_message(device_token, payload)

    def process_failed_sent_messages(self):
        """ Processes messages that were sent AFTER the message that
            caused the connection to be cut. """

        if len(self.sent_messages) > (MAX_MESSAGE_ID - MIN_MESSAGE_ID):
            # As the number of saved sent messages is higher than the
            # number of unique message id's, we cannot work out which
            # ones have been sent and which ones haven't. Either the number
            # of saved sent messages should be decreased or the range
            # of message id's should be increased.
            log.msg("Can't resend messages as the " \
                    "proportion of cached sent messages is higher than" \
                    "the difference between the max message ID and min"
                    "message ID. The number of sent messages stored should " \
                    "be decreased, or the range of message id's increased")
        else:
            log.msg("Resending messages that were sent after the failed " \
                    "message (id: {0})".format(self.message_error))

            # This check is to cover the case where the message counter has
            # has recently been reset, following it hitting the maximum value.
            # We don't want to resend messages that were sent succesfully but
            # have a higher sequence number, so we take into account the number
            # of messages sent since the reset if the error is higher than the
            # current sequence number.
            if len(self.sent_messages) > \
                ((self.sequence_number - MIN_MESSAGE_ID)):
                number_beyond_min = self.sequence_number - MIN_MESSAGE_ID
                max_id_to_resend = MAX_MESSAGE_ID - (len(self.sent_messages) -
                                                     number_beyond_min)
                log.msg("Detected counter reset. NumberBeyondMin: {0}, " \
                        "MaxIDToResend: {1}".format(number_beyond_min,
                                                    max_id_to_resend))
                looped = True
            else:
                max_id_to_resend = MAX_MESSAGE_ID
                looped = False

            for message in self.sent_messages:
                for key, value in message.iteritems():
                    resend = False
                    if looped is True:
                        if key > int(self.message_error):
                            if key < max_id_to_resend or \
                             int(self.message_error) > self.sequence_number:
                                resend = True
                        else:
                            if key < max_id_to_resend and \
                                int(self.message_error) > max_id_to_resend:
                                resend = True
                    else:
                        if key > int(self.message_error):
                            resend = True

                    if resend is True:
                        log.msg("Resending message with id: " + str(key))
                        self.protocol.sendMessage(value[1])

        self.message_error = None

    def clientConnectionLost(self, connector, reason):
        """ Called when the network connection to the APNS has been lost,
            so set the connected flag to False and initiate the reconnection
            process. """

        self._connected = False

        log.msg(("Lost connection to the APNS. Reason: {0}").format(
            reason.getErrorMessage()))

        # Try and work out what the problem is, for informational
        # purposes
        if reason.check(error.TimeoutError):
            log.msg("APNS TimeoutError exception was caught")
        elif reason.check(error.ConnectionLost):
            log.msg("APNS ConnectionLost exception was caught")

        # Add the message to the queue so that upon reconnection,
        # it will try to send the message straight away
        if self.message is not None:
            self.protocol.message = self.message

        ReconnectingClientFactory.clientConnectionLost(self, connector,
                                                       reason)

    def clientConnectionFailed(self, connector, reason):
        """ The connection attempt to the APNS has failed. """

        log.err(("Unable to connect to the APNS. Reason: {0}").format(reason))

        ReconnectingClientFactory.clientConnectionFailed(self, connector,
                                                         reason)

class APNSService(object):
    """ Sets up and controls the instances of the APNS and
        APN Feedback factories. """

    def __init__(self, certificate_file, key_file,
                 error_callback=None, use_sandbox=False,
                 apns_queue_size=1):

        self.error_callback = error_callback
        self.apns_factory = APNSClientFactory(self.handle_error,
                                    apns_queue_size)

        if use_sandbox is True:
            apns_host = APNS_SANDBOX_HOSTNAME
        else:
            apns_host = APNS_HOSTNAME

        reactor.connectSSL(apns_host, APNS_PORT,
                    self.apns_factory,
                    common.APNSClientContextFactory(certificate_file,
                                                  key_file))

    def handle_error(self, error_tuple):
        """ Method which handles error response that have been received from
            the APNS, for example when a token is no longer valid. """

        if self.error_callback is not None:
            invalid_token = 0
            error_value = error_tuple[ERROR_VALUE_INDEX]
            for message in self.apns_factory.sent_messages:
                if message.has_key(int(error_tuple[SENT_MESSAGE_INDEX])):
                    invalid_token = message[int(error_tuple[
                        SENT_MESSAGE_INDEX])][0]
                    break

            response = (error_value, invalid_token)

            self.error_callback(response)

    def send_message(self, device_token, payload):
        """ Initiates the process to send the payload to the
            device with the specified token. """

        self.apns_factory.sendMessage(device_token, payload)

