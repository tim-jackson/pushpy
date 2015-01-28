# pushpy
Framework for sending Push Notifications to iOS, Android and BB10 Devices


### Prerequisities/Dependencies
--------------------
pushpy is written in Python using the Twisted framework (https://twistedmatrix.com); the minimum version requirements are:
* python 2.7.3
* twisted 12.0.0

### Running as a service
--------------------
An application can be written to be run as a standalone service using pushpy - see pushpy_service_demo.tac for an example of how to do this. This is the envisaged way that pushpy applications will be deployed. Providing all dependencies are satisfied, the demo application can be started as a service using the following command:

twistd -y pushpy_service_demo.tac

### Running in a console
--------------------
An application can also be run inside a console session. This is convenient when developing/debugging an application, as all log output can be written straight to the console, but not advisable upon deployment.

python apns_demo.py

### License
--------------------
[BSD 3-Clause / new / simplified](http://opensource.org/licenses/BSD-3-Clause) (see [LICENSE](LICENSE))

