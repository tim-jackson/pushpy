"""common.py: Module which contains common functionality enabling
push notification messages to be sent to various platforms. """

from twisted.internet.ssl import ClientContextFactory
from OpenSSL import SSL

class APNSClientContextFactory(ClientContextFactory):
    """ Represents the context relating to the SSL authentication that
        has to be used when connecting to the APNS. """

    def __init__(self, apns_certificate_file, apns_private_key_file):
        self.context = SSL.Context(SSL.TLSv1_METHOD)
        self.context.use_certificate_file(apns_certificate_file)
        self.context.use_privatekey_file(apns_private_key_file)

    def getContext(self):
        """ Returns the SSL context which should be used when making
            connections to the APNS. This getter exists as it is overriding
            the getContext method in ClientContextFactory, which other
            classes use instead of directly using the variable. """

        return self.context
