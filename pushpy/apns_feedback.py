"""apns_feedback.py: Module which contains functionality which polls
the APNS feedback service for expired/invalid tokens. """

import base64
import struct
import common
from twisted.internet.protocol import ReconnectingClientFactory
from twisted.internet import defer, reactor
from twisted.protocols.basic import LineReceiver
from twisted.python import log
from StringIO import StringIO

APN_HOSTNAME = "feedback.push.apple.com"
APN_SANDBOX_HOSTNAME = "feedback.sandbox.push.apple.com"
APN_FEEDBACK_PORT = 2196
FEEDBACK_INTERVAL = 43200

class APNProcessFeedback(LineReceiver):
    """ Handles the data that is received from the APN feedback service. """

    def __init__(self):
        pass

    def connectionMade(self):
        """ Called when successfully connected to the feedback service. """

        log.msg("Connected to the APN Feedback Service")

    def rawDataReceived(self, data):
        """ Called when data is received from the feedback service. """

        log.msg("Receiving data from the APN Feedback Service")
        self.input.write(data)

    def lineReceived(self, data):
        """ Called when data is received from the feedback service. """

        log.msg("Receiving data from the APN Feedback Service")
        self.input.write(data)

    def connectionLost(self, reason):
        """ Called when the connection is closed by the feedback service (this
            is the behaviour when it has finished sending data. """

        log.msg("Finished receiving data from the Feedback Service.")

        self.factory.process_list(self.input.getvalue())
        self.input.close()

class APNFeedbackClientFactory(ReconnectingClientFactory):
    """ Factory which manages instances of the protocol which connect to the
        APN Feedback Service to retrieve invalid client tokens. """

    def __init__(self, feedback_callback):
        self.deferred = defer.Deferred()
        self.deferred.addCallback(self.process_list)

        self.protocol = APNProcessFeedback()
        self.feedback_callback = feedback_callback

    def buildProtocol(self, addr):
        """ Builds an instance of the APNProcessFeedback protocol. """

        log.msg("Connecting to the APN feedback service")
        self.initialDelay = FEEDBACK_INTERVAL
        self.maxDelay = FEEDBACK_INTERVAL
        self.resetDelay()

        new_protocol = self.protocol
        new_protocol.factory = self
        new_protocol.deferred = self.deferred
        new_protocol.input = StringIO()
        new_protocol.setRawMode()

        return new_protocol

    def process_list(self, data):
        """ Parses a list of tokens received from the feedback service. """

        log.msg("Processing the tokens received from the APN feedback service")

        token_list = []
        header_size = 6

        while data != "":
            try:
                # Format is a 4 byte time followed by a 2 byte token
                # length field
                feedback_time, token_length = struct.unpack_from('!lh', data, 0)
                data = data[header_size:]

                # Extract the token by using the length that has just been
                # retrieved
                token = struct.unpack_from("!{0}s".format(token_length),
                                           data, 0)[0]
                encoded_token = base64.encodestring(token).replace('\n', '')
                token_list.append((feedback_time, encoded_token))
                data = data[token_length:]
            except struct.error:
                log.err("Could not parse data received from the APN " \
                        "Feedback service.")
                break

        log.msg("Finished processing the token list received from " \
                "the APN feedback service")

        self.feedback_callback(token_list)

    def startedConnecting(self, connector):
        """ Called when a connection attempt to the APN feedback service
            has started. """

        log.msg('Attempting to connect to the APN feedback service')

    def clientConnectionLost(self, connector, reason):
        """ Called when the network connection to the APN feedback
            service has been lost. """

        ReconnectingClientFactory.clientConnectionLost(self, connector, reason)

    def clientConnectionFailed(self, connector, reason):
        """ The connection attempt to the APN feedback service has failed. """

        log.err("Unable to connect to the APN feedback service")

        ReconnectingClientFactory.clientConnectionLost(self, connector, reason)

class APNFeedbackService(object):
    """ Sets up and controls the instances of the
        APN Feedback factory. """

    def __init__(self, certificate_file, key_file, feedback_callback,
                 use_sandbox=False):
        self.apns_receiver = APNFeedbackClientFactory(feedback_callback)

        if use_sandbox is True:
            apns_host = APN_SANDBOX_HOSTNAME
        else:
            apns_host = APN_HOSTNAME

        reactor.connectSSL(apns_host, APN_FEEDBACK_PORT,
                    self.apns_receiver,
                    common.APNSClientContextFactory(certificate_file,
                                                  key_file))

