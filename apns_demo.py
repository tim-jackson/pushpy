"""apns_demo.py : Example app which uses the APNS service to send
push notifications. """

import sys
from twisted.internet import reactor
from twisted.python import log
from pushpy import apns, apns_feedback, blackberry, gcm

USE_SANDBOX = True
CERTIFICATE_FILE = "apple_cert.pem"
KEY_FILE = "apple_key.pem"
APNS_QUEUE_SIZE = 100

log.startLogging(sys.stdout)

def handle_apns_send_failure(failure_tuple):
    """ Callback method which deals with tokens that, when attempting
        to send a notification, had an error response returned from
        the APNS. """

    if failure_tuple[0] == 8:
        log.msg("Token {0} will be deleted".format(failure_tuple[1]))
        self._delete_token(failure_tuple[1])
    else:
        log.msg("Error code {0} received when sending message to " \
                "token {1}".format(failure_tuple[0], failure_tuple[1]))

def process_failed_tokens(token_list):
    """ Processes a list of tokens which have been sent by the APN
        feedback service, and represent devices which should no
        longer receive APNS messages. """

    for token in token_list:
        if len(token) >= 2:
            print "Token to delete: {0}".format(token[1])

def send_apns_message(apns_token, payload):
    """ Sends the payload to the APNS token specified. """

    APNS_SERVICE.send_message(apns_token, payload)

APNS_SERVICE = apns.APNSService(CERTIFICATE_FILE, KEY_FILE,
                                     handle_apns_send_failure,
                                     USE_SANDBOX, APNS_QUEUE_SIZE)
APNS_FEEDBACK = apns_feedback.APNFeedbackService(CERTIFICATE_FILE,
                                KEY_FILE, process_failed_tokens,
                                USE_SANDBOX)

reactor.run()

