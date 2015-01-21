from twisted.application import service
from twisted.python.logfile import DailyLogFile
from twisted.python.log import ILogObserver, FileLogObserver
import apns_demo

LOG_FILE = DailyLogFile("pushpy_service_demo.log", ".")

application = service.Application('pushpy')
application.setComponent(ILogObserver, FileLogObserver(LOG_FILE).emit)
SERVICE = service.IServiceCollection(application)

