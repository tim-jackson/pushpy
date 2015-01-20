"""gcm.py: Functionality enabling Push Notification
messages to be sent to the Google Cloud Messaging service. """

import json
import ast
from datetime import datetime
from StringIO import StringIO
from twisted.internet.protocol import Protocol
from twisted.python import log
from twisted.internet.defer import Deferred
from twisted.internet import reactor
from twisted.web.client import Agent
from twisted.internet.ssl import ClientContextFactory
from twisted.web.client import FileBodyProducer
from twisted.web.http_headers import Headers

TOKEN_ERRORS = ['InvalidRegistration', 'NotRegistered']

class WebClientContextFactory(ClientContextFactory):
    """ Context Factory used to connect to the push service
        over SSL. """

    def getContext(self, hostname, port):
        """ Returns a ClientConextFactory used to prepare a
            connection to the Blackberry push service. """

        return ClientContextFactory.getContext(self)

class GCMResponse(Protocol):
    """ Reads the response received from the GCM service
        into the buffer. """

    def __init__(self, callback):
        self.callback = callback
        self.data = ""

    def dataReceived(self, bytes):
        """ Append the bytes received from the GCM service
            to the current block of data. """

        self.data += bytes

    def connectionLost(self, reason):
        """ Called when the connection to the GCM service
            has been lost, indicating that the response message
            has been received. """

        log.msg(self.data)
        self.callback.callback(self.data)

class GCMService(object):
    """ Sets up and controls the instances of the GCM client
        factory. """

    def __init__(self, hostname, application_id, application_key,
                 error_callback, update_callback,
                 notification_hostname=None):

        contextFactory = WebClientContextFactory()
        self.android_hostname = hostname
        self.notification_hostname = notification_hostname
        self.application_id = application_id
        self.application_key = application_key
        self.error_callback = error_callback
        self.update_callback = update_callback

        self.agent = Agent(reactor, contextFactory)

    def errorReceived(self, error_detail):
        """ Logs an error message when an error is detected. """

        log.err("Error thrown when executing request: {0}".format(
            error_detail))

    def responseReceived(self, response, device_list):
        """ Creates a GCMResponse protocol when a response is
            received from the web service request. """

        if response.code == 200:
            deferred = Deferred()
            response.deliverBody(GCMResponse(deferred))
            deferred.addCallback(self.process_response, device_list)
        else:
            log.err("Did not receive 200 response: {0}".
                    format(str(response.code)))

    def process_response(self, gcm_response, device_list):
        """ Processes the response from the GCM. """

        try:
            parsed_response = ast.literal_eval(gcm_response)
        except ValueError:
            log.err("Unable to parse response ({0}) from GCM: {0}".format(\
                                                        gcm_response))
            return

        if parsed_response['failure'] > 0 or \
                parsed_response['canonical_ids'] > 0:
            self.process_fail_response(parsed_response, device_list)
        else:
            log.msg("GCM message accepted")

    def process_fail_response(self, response, device_list):
        """ Proceses the fail response to determine what action should be
            taken with the messages that were not accepted by the GCM. """

        for device_number, gcm_response in enumerate(response['results']):
            response_tuple = gcm_response.items()
            for status, reason in response_tuple:
                if status == "error":
                    if reason in TOKEN_ERRORS:
                        log.msg("Token {0} should be removed from the " \
                                "database. Reason: {1}".format(\
                                device_list[device_number], reason))
                        self.error_callback(device_list[device_number])
                        break
                    else:
                        log.msg("Token {0} returned error response {1} but " \
                            "should not be removed at this time".format(\
                                device_list[device_number], reason))
                elif status == "registration_id":
                    log.msg("Token {0} should be updated in the " \
                            "database. New Token: {1}".format(\
                            device_list[device_number], reason))
                    self.update_callback(device_list[device_number], reason)

    def construct_message(self, device_list, message_header, message_text,
                          user_notification=False):
        """ Creates a message in the defined format to send to the
            GCM service. """

        message_time = datetime.utcnow().strftime("%H:%M.%S")

        if user_notification is True:
            payload = json.dumps({"data" : {message_header : message_text,
                                   "time" : message_time },
                                   "to" : device_list[0] })
        else:
            payload = json.dumps({"data" : {message_header : message_text,
                                   "time" : message_time },
                                   "registration_ids" : device_list })

        return payload

    def process_api_response(self, api_response,
                             message_header, message_text):
        """ Processes the response from the API which should have created a
            notification key for a group of devices. """

        user_notification_key = api_response['notification_key']

        self._compose_submit_message(user_notification_key, message_header,
                                     message_text)

    def _compose_submit_message(self, user_notification_key, message_header,
                                message_text):

        payload = self.construct_message(user_notification_key, message_header,
                                         message_text,
                                         user_notification=True)
        self._submit_request(user_notification_key, payload)

    def send_message(self, device_list, message_header,
                     message_text):
        """ Constructs a message from the device list and payload provided. """

        payload = self.construct_message(device_list, message_header,
                                         message_text,
                                         user_notification=False)
        self._submit_request(device_list, payload)

    def _submit_request(self, device_list, payload):
        """ Private method which wraps the payload in a HTTP request and
            submits it as a POST method to the GCM service.
            Request is made using a Deferred object to ensure that it
            is a non blocking event when waiting for the repsonse. """

        body = FileBodyProducer(StringIO(payload))

        deferred_request = self.agent.request('POST', self.android_hostname,
            Headers({'Authorization': ['key=%s' % self.application_key],
                     'Content-type': ['application/json']}),
                     bodyProducer=body)

        deferred_request.addCallback(self.responseReceived, device_list)
        deferred_request.addErrback(self.errorReceived)

        return deferred_request

