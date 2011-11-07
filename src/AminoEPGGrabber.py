#/usr/bin/env python

"""
A XMLTV compatible EPG grabber for the Amino EPG.

Supported TV networks:
OnsNetEindhoven
OnsBrabantNet
"""

# READ ME:
# To change the setup of the grabber, please edit the 'main'
# function at the bottom of the file.

#Stuff that still needs to be added:
#* Support interface selection
#* Add exception handling so we can operate without pytz if not present
#* Read configuration file
#* Support only processing channels specified in configuration

from datetime import datetime, date, timedelta
from xml.dom.minidom import Document
import pytz
import httplib
import socket
import StringIO
import gzip
import json
import cPickle
import os
import re
import time

#===============================================================================
# The internal data struture used in the AminoEPGGrabber to
# store the EPG data is as follows:
# (dict)
#    epgData
#        channelname:(dict)
#            programid:(dict)
#                starttime
#                stoptime
#                title
#                sub-title
#                desc
#                actors []
#                directors []
#                categories []
#===============================================================================

class AminoEPGGrabber(object):
    """
    Class AminoEPGGrabber implements the grabbing and processing
    functionality needed for generating an XMLTV guide from the
    supplied location.
    """
    def __init__(self):
        # Set up defaults
        self.epgServer = "w1.zt6.nl"
        self.maxDays = 7
        self.details = True
        self.xmltvFile = "aminoepg.xml"
        self.databaseFile = "aminograbber.pkl"
        
        self._timezone = pytz.timezone("Europe/Amsterdam")
        self._epgdata = dict()
        self._xmltv = None
        self._epgConnection = None
        
    #===============================================================================
    # Getters and setters
    #===============================================================================
    def set_timezone(self, timezoneName):
        """Set the timezone we are working in, by name"""
        self._timezone = pytz.timezone(timezoneName)
    
    def get_timezone(self):
        """Return the name of the currently set timezone"""
        return self._timezone.zone
    
    timezone = property(get_timezone, set_timezone)

    #===============================================================================
    # Public functions
    #===============================================================================
    def loadDatabase(self):
        """
        This function will load a database file into memory.
        It will overwrite the current in-memory data
        """
        # Only load if file exists
        if os.path.isfile(self.databaseFile):
            dbFile = open(self.databaseFile, "r")
            self._epgdata = cPickle.load(dbFile)
            dbFile.close()
        
        # Determine current date
        today = date.today()
        
        # Remove programs that stopped before 'now'
        for _, programs in self._epgdata.iteritems():
            for programId in programs.keys():
                stopDate = datetime.strptime(programs[programId]["stoptime"][:8], "%Y%m%d").date()
                if stopDate < today:
                    # Remove program
                    del programs[programId]
                else:
                    # Set program as not grabbed
                    programs[programId]["grabbed"] = False
        
    def writeDatabase(self):
        """
        This function will write the current in-memory EPG data to
        a database file.
        NOTE: Programs not found in the downloaded EPG will not be saved!
        """
        # Clean up old data (programs that weren't grabbed)
        for _, programs in self._epgdata.iteritems():
            for programId in programs.keys():
                if not programs[programId].has_key("grabbed") or \
                not programs[programId]["grabbed"]:
                    del programs[programId]
        
        # Write dictionary to disk
        dbFile = open(self.databaseFile, "w")
        cPickle.dump(self._epgdata, dbFile)
        dbFile.close()
        
    def grabEpg(self):
        """
        This function will grab the EPG data from the EPG server.
        If an existing database file was loaded, that data will be updated.
        """
        # Grab EPG data for all days
        for grabDay in range(self.maxDays):
            for dayPart in range(0, 8):
                grabDate = date.today() + timedelta(days=grabDay)
                print "Grabbing", str(grabDate), "part", dayPart,
                print "(day " + str(grabDay+1) + "/" + str(self.maxDays) + ")"
                
                try:
                    # Set up new connection to EPG server
                    self._epgConnection = httplib.HTTPConnection(self.epgServer)
            
                    # Get basic EPG
                    fileId = grabDate.strftime("%Y%m%d.") + str(dayPart)
                    requestUrl = "/epgdata/epgdata." + fileId + ".json.gz"
                    
                    try:
                        self._epgConnection.request("GET", requestUrl)
                        response = self._epgConnection.getresponse()
                        epgData = response.read()
                        
                        if response.status != 200:
                            print "HTTP Error %s (%s). Failed on fileid %s." % (response.status,
                                                                                response.reason,
                                                                                fileId)
                            break # break loop, no more days
                        
                    except socket.error, error:
                        print "Failed to download '" + fileId + "'"
                        print "The error was:", error
                        return False # Return with error
                    except httplib.CannotSendRequest, error:
                        print "Error occurred on HTTP connection. Connection lost before sending request."
                        print "The error was:", error
                        return False # Return with error
                    except httplib.BadStatusLine, error:
                        print "Error occurred on HTTP connection. Bad status line returned."
                        print "The error was:", error
                        return False # Return with error
                    
                    # Decompress and retrieve data
                    compressedStream = StringIO.StringIO(epgData)
                    rawData = gzip.GzipFile(fileobj=compressedStream).read()
                    basicEpg = json.loads(rawData, "UTF-8")
                    
                    # Close StringIO
                    compressedStream.close()
                    
                    # Process basic EPG
                    self._processBasicEPG(basicEpg)
                
                finally:
                    # Make sure connection gets closed
                    self._epgConnection.close()
                    self._epgConnection = None
                
        return True # Return with success
                
    def writeXmltv(self):
        """
        This function will write the current in-memory EPG data to an XMLTV file.
        NOTE: Programs not found in the downloaded EPG will not be saved!
        """
        # Set up XML tree
        self._xmltv = Document() # create new XML document   
        
        # Create main <TV> tag
        tvTag = self._xmltv.createElement("tv")
        tvTag.setAttribute("source-info-url", self.epgServer)
        tvTag.setAttribute("source-info-name",
                           "Local amino EPG server")
        tvTag.setAttribute("generator-info-name",
                           "AminoEPGGrabber v0.0.1 (C) 2011 Jeroen Bogers")
        tvTag.setAttribute("generator-info-url",
                           "http://gathering.tweakers.net")
        self._xmltv.appendChild(tvTag)
        
        # Add channels to XML
        for channel in sorted(self._epgdata.keys()):
            channelTag = self._xmltv.createElement("channel")
            channelTag.setAttribute("id", channel)
            channelDisplayNameTag = self._xmltv.createElement("display-name")
            channelDisplayNameTag.setAttribute("lang", "nl")
            channelDisplayNameTagText = self._xmltv.createTextNode(channel)
            channelDisplayNameTag.appendChild(channelDisplayNameTagText)
            channelTag.appendChild(channelDisplayNameTag)
            tvTag.appendChild(channelTag)
            
        # Add programs to XML
        for channel, programs in sorted(self._epgdata.items()):
            for _, program in sorted(programs.items()):
                self._addProgramToXML(channel, program, tvTag)
        
        # Generate XML string, fixing it with a regex (toprettyxml has a formatting bug)
        # Set up regular expressions to fix XML string
        xml_reformat = re.compile('>\n\s+([^<>\s].*?)\n\s+</', re.DOTALL)
        rawXml = self._xmltv.toprettyxml(indent="  ", encoding="UTF-8")
        prettyXml = xml_reformat.sub('>\g<1></', rawXml)
    
        # Write XMLTV file to disk
        outFile = open(self.xmltvFile, "w")
        outFile.write(prettyXml)
        outFile.close()
        
    #===============================================================================
    # Private functions
    #===============================================================================
    def _processBasicEPG(self, basicEpg):
        """
        Takes the loaded EPG data and converts it to the in-memory
        structure. If the program is not in memory, or differs from
        the in memory data, the details are retrieved.
        """
        for channel, grabbedPrograms in basicEpg.iteritems():
            # Check if data for channel is loaded yet
            if not self._epgdata.has_key(channel):
                self._epgdata[channel] = dict()
            
            # Store all program data
            for grabbedProgram in grabbedPrograms:
                # Convert to internal structure
                try:
                    programId = grabbedProgram["id"]
                    program = dict()
                    program["grabbed"] = True
                    program["starttime"] = self._convertTimestamp(grabbedProgram["start"])
                    program["stoptime"] = self._convertTimestamp(grabbedProgram["end"])
                    program["title"] = grabbedProgram["name"]
                except KeyError:
                    # Program with incomplete data (most likely missing 'name').
                    # Cannot create valid XMLTV entry, so skip (data will be updated on a next run when it is available)
                    continue
                
                # Add every program to the internal data structure
                if self._epgdata[channel].has_key(programId):
                    # Existing program, verify it has not been changed
                    stored = self._epgdata[channel][programId]
                    if stored["starttime"] == program["starttime"] and \
                    stored["stoptime"] == program["stoptime"] and \
                    stored["title"] == program["title"]:
                        # Mark stored program as 'grabbed' and skip to next
                        stored["grabbed"] = True
                        continue
                    else:
                        # Changed program, remove from storage and grab new data
                        del self._epgdata[channel][programId]
                
                # New program or program with changes, get details
                if self.details:
                    self._grabDetailedEPG(programId, program)
                
                # Add program to internal storage
                self._epgdata[channel][programId] = program
                
    def _grabDetailedEPG(self, programId, program):
        """Download the detailed program data for the specified program"""
        
        # Generate details URL 
        programIdGroup = programId[-2:]
        detailUrl = "/epgdata/" + programIdGroup + "/" + programId + ".json"
        
        # Try to download file
        try:
            self._epgConnection.request("GET", detailUrl)
            response = self._epgConnection.getresponse()
            if response.status != 200:
                return # No data can be downloaded, return
            
        except (socket.error, httplib.CannotSendRequest, httplib.BadStatusLine):
            # Error in connection. Close existing connection.
            self._epgConnection.close()
            
            # Wait for network to recover
            time.sleep(10)
            
            # Reconnect to server and retry
            try:
                self._epgConnection = httplib.HTTPConnection(self.epgServer)
                self._epgConnection.request("GET", detailUrl)
                response = self._epgConnection.getresponse()
                if response.status != 200:
                    return # No data can be downloaded, return
                
            except (socket.error, httplib.CannotSendRequest, httplib.BadStatusLine):
                # Connection remains broken, return (error will be handled in grabEpg function)
                return
        
        detailEpg = json.load(response, "UTF-8")
        
        # Episode title
        if detailEpg.has_key("episodeTitle") and len(detailEpg["episodeTitle"]) > 0:
            program["sub-title"] = detailEpg["episodeTitle"]
            
        # Detailed description
        if detailEpg.has_key("description") and len(detailEpg["description"]) > 0:
            program["desc"] = detailEpg["description"]
            
        # Credits
        program["credits"] = dict()

        if detailEpg.has_key("actors") and len(detailEpg["actors"]) > 0:
            program["credits"]["actor"] = []
            for actor in detailEpg["actors"]:
                program["credits"]["actor"].append(actor)
                
        if detailEpg.has_key("directors") and len(detailEpg["directors"]) > 0:
            program["credits"]["director"] = []
            for director in detailEpg["directors"]:
                program["credits"]["director"].append(director)
                
        if detailEpg.has_key("presenters") and len(detailEpg["presenters"]) > 0:
            program["credits"]["presenter"] = []
            for presenter in detailEpg["presenters"]:
                program["credits"]["presenter"].append(presenter)
                
        if detailEpg.has_key("commentators") and len(detailEpg["commentators"]) > 0:
            program["credits"]["commentator"] = []
            for presenter in detailEpg["commentators"]:
                program["credits"]["commentator"].append(presenter)
                
        # Genres
        if detailEpg.has_key("genres") and len(detailEpg["genres"]) > 0:
            program["categories"] = []
            for genre in detailEpg["genres"]:
                program["categories"].append(genre)
                
        # Aspect ratio
        if detailEpg.has_key("aspectratio") and len(detailEpg["aspectratio"]) > 0:
            program["aspect"] = detailEpg["aspectratio"]
            
        # TODO: NICAM ratings (nicamParentalRating and nicamWarning)
                
    def _addProgramToXML(self, channel, program, xmltag):
        """Add program to XML tree under the specified tag"""
        # Construct programme tag
        programmeTag = self._xmltv.createElement("programme")
        programmeTag.setAttribute("start", program["starttime"])
        programmeTag.setAttribute("stop", program["stoptime"])
        programmeTag.setAttribute("channel", channel)
        xmltag.appendChild(programmeTag)
        
        # Construct title tag
        titleTag = self._xmltv.createElement("title")
        titleTag.setAttribute("lang", "nl")
        titleTagText = self._xmltv.createTextNode(program["title"])
        titleTag.appendChild(titleTagText)
        programmeTag.appendChild(titleTag)
        
        # Subtitle
        if program.has_key("sub-title"):
            # Add sub-title tag
            subtitleTag = self._xmltv.createElement("sub-title")
            subtitleTag.setAttribute("lang", "nl")
            subtitleTagText = self._xmltv.createTextNode(program["sub-title"])
            subtitleTag.appendChild(subtitleTagText)
            programmeTag.appendChild(subtitleTag)
            
        # Description
        if program.has_key("desc"):
            # Add desc tag
            descriptionTag = self._xmltv.createElement("desc")
            descriptionTag.setAttribute("lang", "nl")
            descriptionTagText = self._xmltv.createTextNode(program["desc"])
            descriptionTag.appendChild(descriptionTagText)
            programmeTag.appendChild(descriptionTag)
            
        # Credits (directors, actors, etc)
        if program.has_key("credits") and len(program["credits"]) > 0:
            # Add credits tag
            creditsTag = self._xmltv.createElement("credits")
            
            # Add tags for each type of credits (in order, so XMLTV stays happy)
            #creditTypes = ["director", "actor", "writer", "adapter",
            #               "producer", "composer", "editor", "presenter",
            #               "commentator", "guest"]
            creditTypes = ["director", "actor", "presenter", "commentator"]
            creditsDict = program["credits"]
            
            for creditType in creditTypes:
                if creditsDict.has_key(creditType):
                    for person in creditsDict[creditType]:
                        personTag = self._xmltv.createElement(creditType)
                        personTagText = self._xmltv.createTextNode(person)
                        personTag.appendChild(personTagText)
                        creditsTag.appendChild(personTag)
                    
            programmeTag.appendChild(creditsTag)
            
        # Categories
        if program.has_key("categories"):
            # Add multiple category tags
            for category in program["categories"]:
                categoryTag = self._xmltv.createElement("category")
                categoryTag.setAttribute("lang", "nl")
                categoryTagText = self._xmltv.createTextNode(category)
                categoryTag.appendChild(categoryTagText)
                programmeTag.appendChild(categoryTag)
                
        # Aspect ratio
        if program.has_key("aspect"):
            # Add aspect tag
            aspectTag = self._xmltv.createElement("aspect")
            aspectTagText = self._xmltv.createTextNode(program["aspect"])
            aspectTag.appendChild(aspectTagText)
            programmeTag.appendChild(aspectTag)
    
    def _convertTimestamp(self, timestamp):
        """Convert downloaded timestamp to XMLTV compatible time string"""
        startTime = datetime.fromtimestamp(timestamp, self._timezone)
        return startTime.strftime("%Y%m%d%H%M%S %z")


def main():
    """
    Main entry point of program.
    This function will read the configuration file and start the grabber.
    """
    print "AminoEPGGrabber started on " + str(datetime.now())
    
    # Create grabber class
    grabber = AminoEPGGrabber()
    
    # Override defaults
    # Override the EPG server location if you are in a different
    # network, or when you need to use a direct IP address.
    grabber.epgServer = "w1.zt6.nl"
    #grabber.epgServer = "192.168.0.102:8080"
    
    # By default the grabber will grab 7 days, which is the usual
    # maximum of days that are offered, so make sure you only
    # decrease the number of days!
    #grabber.maxDays = 7
    
    # By default the grabber will grab details about a program, like
    # the episode title and description. If you set the variable
    # to 'False' only program title and broadcast times are retrieved.
    # This retrieval is a lot faster.
    # NOTE: If you change this value, delete the database file. If you
    # don't, only newly grabbed programs will be affected.
    #grabber.details = True
    
    # You can specify different filenames and locations for the
    # generated EPG file and the database, if so desired.
    #grabber.xmltvFile = "aminoepg.xml"
    #grabber.databaseFile = "aminograbber.pkl"
    
    # Load saved database
    grabber.loadDatabase()
    
    # Grab EPG from IPTV network
    grabber.grabEpg()
    
    # Write database
    grabber.writeDatabase()
    
    # Write XMLTV file
    grabber.writeXmltv()
    
    print "AminoEPGGrabber finished on " + str(datetime.now())

if __name__ == "__main__":
    main()
    