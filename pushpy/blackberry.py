"""blackberry.py: Module which contains functionality enabling push notification
messages to be sent to the Blackberry Push Service. """

from datetime import datetime, timedelta
import base64
import uuid
from StringIO import StringIO
from twisted.internet.protocol import Protocol
from twisted.python import log
from twisted.internet import reactor
from twisted.web.client import Agent
from twisted.internet.ssl import ClientContextFactory
from twisted.web.client import FileBodyProducer
from twisted.web.http_headers import Headers

MAX_DELAY = 2
BOUNDARY = "boundary-marker"
SUCCESS_CODE = "1001"
MESSAGE_TEMPLATE = """
 --{boundary}--
Content-Type: application/xml
<?xml version="1.0"?>
<!DOCTYPE pap PUBLIC "-//WAPFORUM//DTD PAP 2.1//EN"
"http://www.openmobilealliance.org/tech/DTD/pap_2.1.dtd">
<pap>
  <push-message push-id="{unique_push_id}"
                source-reference="{application_id}"
                deliver-before-timestamp="{timestamp}">
    {device_segment}
    <quality-of-service delivery-method="confirmed"/>
  </push-message>
</pap>
--{boundary}--
Content-Encoding: binary
Content-Type: text/html

{content}

 --{boundary}--
 """

class WebClientContextFactory(ClientContextFactory):
    """ Context Factory used to connect to the push service
        over SSL. """

    def getContext(self, hostname, port):
        """ Returns a ClientConextFactory used to prepare a
            connection to the Blackberry push service. """

        return ClientContextFactory.getContext(self)

class BlackberryResponse(Protocol):
    """ Protocol used to read the response from the request that is sent
        to the Blackberry Push Service. """

    def __init__(self):
        self.data = ""

    def dataReceived(self, bytes):
        """ Append the bytes received to the current block of data. """

        self.data += bytes

    def connectionLost(self, reason):
        """ Called when the connection to the push service has been lost,
            indicating. """

        if SUCCESS_CODE not in self.data:
            log.err("Blackberry Push Message was not accepted for " \
                    "processing: {0}".format(reason.getErrorMessage()))
        else:
            log.msg("Blackberry Push Message was accepted")

class BlackberryService(object):
    """ Sets up and controls the instances of the Blackberry client
        factory. """

    def __init__(self, hostname, application_id, application_password):
        contextFactory = WebClientContextFactory()

        self.blackberry_hostname = hostname
        self.application_id = application_id
        self.application_password = application_password

        self.agent = Agent(reactor, contextFactory)

    def errorReceived(self, error_detail):
        """ Callback which is invoked when an error is detected when
            attempting to send a request to the push service. """

        log.err("Error thrown when executing request: {0}".format(error_detail))

    def responseReceived(self, response):
        """ Callback which is invoked when a response is received from the
            push service. Invokes the response protocol to read the contents
            of the body contained in the response. """

        if response.code == 200:
            response.deliverBody(BlackberryResponse())
        else:
            log.err("Did not receive 200 response: {0}".
                    format(str(response.code)))

    def construct_message(self, device_list, message_text):
        """ Creates a new message with the recipients as specified in
            the device list, with the payload provided. """

        device_segment = ""
        message_id = str(uuid.uuid4())
        timestamp = (datetime.utcnow() +
                     timedelta(hours=MAX_DELAY)). \
                     strftime("%Y-%m-%dT%H:%M:%SZ")

        for device in device_list:
            device_segment += "<address address-value=\"{0}\"/>".format(device)

        payload = MESSAGE_TEMPLATE.format(timestamp=timestamp,
                              content=message_text,
                              unique_push_id = message_id,
                              boundary=BOUNDARY,
                              device_segment = device_segment,
                              application_id=self.application_id)

        return payload

    def send_message(self, device_list, message_text):
        """ Constructs a message from the device list and payload provided. """

        payload = self.construct_message(device_list, message_text)

        self._submit_request(payload)

    def _submit_request(self, payload):
        """ Private method which wraps the payload in a HTTP request and
            submits it as a POST method to the Blackberry push service.
            Request is made using a Deferred object to ensure that it
            is a non blocking event when waiting for the repsonse. """

        body = FileBodyProducer(StringIO(payload))

        deferred_request = self.agent.request('POST', self.blackberry_hostname,
            Headers({'User-Agent': ['Push notify'],
                     'Authorization': ['Basic %s' % base64.b64encode("%s:%s" %
                                                (self.application_id,
                                                 self.application_password))],
                     'Content-type': ['multipart/related; \
                                      boundary={boundary}; \
                                      type=application/xml; \
                                      charset=us-ascii'.format(
                                      boundary=BOUNDARY)]}),
                                      bodyProducer=body)

        deferred_request.addCallback(self.responseReceived)
        deferred_request.addErrback(self.errorReceived)

        return deferred_request

