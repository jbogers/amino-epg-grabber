# Requirements #

Before you can use the AminoEPGGrabber, you will need to have a few things installed on your machine.

You will need the following programms:
  * **Python 2.7**
  * **pytz** a Python library for time zone definitions
  * **lxml** a Python library for XML operations

## Python 2.7 ##

You can get Python 2.7 from http://www.python.org/.
Note that you should not download a python 3.x version. These use a different syntax that is not supported by the AminoEPGGrabber.

If you OS has a bundled Python 2.7 package, it is prefered that you install that version, instead of a separate version from python.org.

Windows users should use the python.org version. Both 32 and 64 bit versions are supported.

Complete installing Python before installing pytx and lxml.

## pytz ##

Pytz can be found on http://pytz.sourceforge.net/.

If you OS has a bundled pytz package, it is prefered that you install that version, instead of a separate version from python.org.

Windows users, and other OS users that do not have a bundled pytz package available, can download the pytz package from PyPi: http://pypi.python.org/pypi/pytz/
Make sure to follow the installation instructions from the PyPi page.

## lxml ##

Lxml can be found on http://lxml.de/.

If you OS has a bundled lxml package, it is prefered that you install that version, instead of a separate version from python.org.

Windows users, and other OS users that do not have a bundled lxml package available, can download the lxml package from PyPi: http://pypi.python.org/pypi/lxml
You should install at least lxml version 2.3.

For Windows users it is recommended to install version 2.3, since that is currently the latest version of lxml that has been precompiled.
Other OS users can either install version 2.3, or any higher version.

# Installation #

Create a folder on your hard driver where you want to install and run AminoEPGGrabber from.

Download the zip file from the google code site (http://code.google.com/p/amino-epg-grabber/downloads/list) and extract the contents to the folder you just created.

Edit the config.xml file to set up the grabber as you like. Explanations for each configuration option can be found in the configuration file.

To run the grabber on Windows, execute the batch file (AminoEPGGrabber.bat).
To run the grabber on another OS (or directly from the command line in Windows), go the the folder where the grabber was installed and enter the following command:<br>
<code>python AminoEPGGrabber.py</code>

It is recommended to run the grabber once a day, so the XMLTV file gets refreshed regularly. You can do this with task manager (Windows), crontab (<code>*</code>nix systems) or a similar tool.<br>
<br>
<b>IMPORTANT:</b> Avoid running the grabber on busy times (15:00 - 22:00), to limit the strain on the EPG server. The grabber has a higher load on the EPG server then a set-top box!