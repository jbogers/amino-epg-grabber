#!/usr/bin/env python

"""
A XMLTV compatible EPG grabber for the Amino EPG.

The grabber should function for any provider that supplies IPTV from Glashart Media.
"""

# Set program version
VERSION = "v0.5"

from datetime import datetime, date, timedelta
from lxml import etree
import pytz
import httplib
import socket
import StringIO
import gzip
import json
import cPickle
import os
import time
import inspect
import sys

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

GRABBERDIR = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))

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
        self.downloadlogo = False
        self.logoStore = None
        self.xmltvFile = "aminoepg.xml"
        self.databaseFile = "aminograbber.pkl"
        self.channelDict = {}
        
        self._timezone = pytz.timezone("Europe/Amsterdam")
        self._epgdata = dict()
        self._xmltv = None
        self._epgConnection = None
        self._foundLogos = dict()
        
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
    def loadConfig(self, configFile):
        """Load the configuration from the given config file"""
        
        try:
            configTree = etree.parse(configFile)
            config = configTree.getroot()
            
            if config.tag != "AminoEpgConfig":
                print >> sys.stderr, "The config.xml file does not appear to be a valid AminoEPGGrabber configuration document."
                sys.exit(1)
                
            # Try to read each config tag
            server = config.find("server")
            if server != None:
                value = server.text.strip()
                if value != "":
                    self.epgServer = value
                
            maxdays = config.find("maxdays")
            if maxdays != None:
                try:
                    value = int(maxdays.text)
                    if value < 7: # Make sure only value < 7 are set (7 is default)
                        self.maxDays = value
                except ValueError:
                    pass # Invalid value, ignore
                
            grabdetails = config.find("grabdetails")
            if grabdetails != None:
                value = grabdetails.text.lower()
                if value == "false": # True is default, so override to false only
                    self.details = False
                    
            downloadlogo = config.find("downloadlogo")
            if downloadlogo != None:
                value = downloadlogo.text.lower()
                if value == "true": # False is default, so override to false only
                    self.downloadlogo = True
                    
                    if downloadlogo.attrib.has_key("location"):
                        location = downloadlogo.attrib["location"].strip()
                        if location != "":
                            self.logoStore = location
                            
            xmltvfile = config.find("xmltvfile")
            if xmltvfile != None:
                value = xmltvfile.text.strip()
                if value != "":
                    self.xmltvFile = value
                    
            databasefile = config.find("databasefile")
            if databasefile != None:
                value = databasefile.text.strip()
                if value != "":
                    self.databaseFile = value
                    
            channellist = config.find("channellist")
            if channellist != None:
                # Channel list found, parse all entries
                channelDict = {}
                for channel in channellist.findall("channel"):
                    # Skip channels that are missing an 'id'
                    if not channel.attrib.has_key("id"):
                        continue
                    
                    # Add channel to channelDict (overwriting existing entry0
                    channelDict[channel.attrib["id"].strip()] = channel.text.strip()
                
                # Replace default channel dict with loaded dict
                self.channelDict = channelDict
            
        except etree.XMLSyntaxError as ex:
            print >> sys.stderr, "Error parsing config.xml file: %s" % ex
            sys.exit(1) # Quit with error code
        except EnvironmentError as ex:
            print >> sys.stderr, "Error opening config.xml file: %s" % ex
            sys.exit(1) # Quit with error code
    
    
    def loadDatabase(self):
        """
        This function will load a database file into memory.
        It will overwrite the current in-memory data
        """
        # Only load if file exists
        databaseFile = os.path.join(GRABBERDIR, self.databaseFile)
        if os.path.isfile(databaseFile):
            dbFile = open(databaseFile, "r")
            self._epgdata = cPickle.load(dbFile)
            dbFile.close()
            
        # Remove channels that are not in the channel list
        if len(self.channelDict) > 0:
            for channel in self._epgdata.keys():
                if not self.channelDict.has_key(channel):
                    del self._epgdata[channel]
        
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
        databaseFile = os.path.join(GRABBERDIR, self.databaseFile)
        dbFile = open(databaseFile, "w")
        cPickle.dump(self._epgdata, dbFile)
        dbFile.close()
        
    def grabEpg(self):
        """
        This function will grab the EPG data from the EPG server.
        If an existing database file was loaded, that data will be updated.
        """
        # Report settings to user
        print "Grabbing EPG using the following settings:"
        print "Server to download from: %s" % self.epgServer
        print "Number days of to grab : %s" % self.maxDays
        print "Detailed program info  : %s" % ("Yes" if self.details else "No")
        print "Download channel logo  : %s" % ("Yes" if self.downloadlogo else "No")
        print "Writing XMLTV file to  : %s" % self.xmltvFile
        print "Using database file    : %s" % self.databaseFile
        print "Grabbing EPG for %d channels." % len(self.channelDict)
        print ""
        
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
                        response.close()
                        
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
        # Set up XML tree and create main <TV> tag
        self._xmltv = etree.Element("tv",
                                    attrib = {"source-info-url"     : self.epgServer,
                                              "source-info-name"    : "Local amino EPG server",
                                              "generator-info-name" : "AminoEPGGrabber %s (C) 2012 Jeroen Bogers" % VERSION,
                                              "generator-info-url"  : "http://gathering.tweakers.net"}
                                    )
        
        # Add channels to XML
        for channel in sorted(self._epgdata.keys()):
            channelTag = etree.Element("channel", id = channel)
            channelDisplayNameTag = etree.Element("display-name", lang = "nl")
            if self.channelDict.has_key(channel):
                channelDisplayNameTag.text = self.channelDict[channel]
            else:
                channelDisplayNameTag.text = channel
            channelTag.append(channelDisplayNameTag)
            
            # Add icon link, if available
            if self._foundLogos.has_key(channel):
                logoLink = "file://%s" % self._foundLogos[channel]
                channelIconTag = etree.Element("icon", src = logoLink)
                channelTag.append(channelIconTag)
                
            self._xmltv.append(channelTag)
            
        # Add programs to XML
        for channel, programs in sorted(self._epgdata.items()):
            for _, program in sorted(programs.items()):
                self._xmltv.append(self._getProgramAsElement(channel, program))
                
        # Write XMLTV file to disk
        xmltvFile = os.path.join(GRABBERDIR, self.xmltvFile)
        outFile = open(xmltvFile, "w")
        outFile.write(etree.tostring(self._xmltv, pretty_print = True, xml_declaration = True, encoding='UTF-8'))
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
            # Ignore channels not in the channel list (if given)
            if len(self.channelDict) > 0 and not self.channelDict.has_key(channel):
                continue
            
            # Check if data for channel is loaded yet
            if not self._epgdata.has_key(channel):
                self._epgdata[channel] = dict()
                
            # Check if channel icon needs to be downloaded
            if self.downloadlogo:
                self._getLogo(channel)
            
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
                response.read() # Force response buffer to be emptied
                response.close()
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
                    response.read() # Force response buffer to be emptied
                    response.close()
                    return # No data can be downloaded, return
                
            except (socket.error, httplib.CannotSendRequest, httplib.BadStatusLine):
                # Connection remains broken, return (error will be handled in grabEpg function)
                return
        
        detailEpg = json.load(response, "UTF-8")
        response.close()
        
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
                
    def _getProgramAsElement(self, channel, program):
        """Returns the specified program as an LXML 'Element'"""
        
        # Construct programme tag
        programmeTag = etree.Element("programme",
                                     start      = program["starttime"],
                                     stop       = program["stoptime"],
                                     channel    = channel)
        
        # Construct title tag
        titleTag = etree.Element("title", lang = "nl")
        titleTag.text = program["title"]
        programmeTag.append(titleTag)
        
        # Subtitle
        if program.has_key("sub-title"):
            # Add sub-title tag
            subtitleTag = etree.Element("sub-title", lang = "nl")
            subtitleTag.text = program["sub-title"]
            programmeTag.append(subtitleTag)
            
        # Description
        if program.has_key("desc"):
            # Add desc tag
            descriptionTag = etree.Element("desc", lang = "nl")
            descriptionTag.text = program["desc"]
            programmeTag.append(descriptionTag)
            
        # Credits (directors, actors, etc)
        if program.has_key("credits") and len(program["credits"]) > 0:
            # Add credits tag
            creditsTag = etree.Element("credits")
            
            # Add tags for each type of credits (in order, so XMLTV stays happy)
            #creditTypes = ["director", "actor", "writer", "adapter",
            #               "producer", "composer", "editor", "presenter",
            #               "commentator", "guest"]
            creditTypes = ["director", "actor", "presenter", "commentator"]
            creditsDict = program["credits"]
            
            for creditType in creditTypes:
                if creditsDict.has_key(creditType):
                    for person in creditsDict[creditType]:
                        personTag = etree.Element(creditType)
                        personTag.text = person
                        creditsTag.append(personTag)
                    
            programmeTag.append(creditsTag)
            
        # Categories
        if program.has_key("categories"):
            # Add multiple category tags
            for category in program["categories"]:
                categoryTag = etree.Element("category", lang = "nl")
                categoryTag.text = category
                programmeTag.append(categoryTag)
                
        # Aspect ratio
        if program.has_key("aspect"):
            # Add video tag, containing aspect tag
            videoTag = etree.Element("video")
            aspectTag = etree.Element("aspect")
            aspectTag.text = program["aspect"]
            videoTag.append(aspectTag)
            programmeTag.append(videoTag)
            
        return programmeTag
    
    def _convertTimestamp(self, timestamp):
        """Convert downloaded timestamp to XMLTV compatible time string"""
        startTime = datetime.fromtimestamp(timestamp, self._timezone)
        return startTime.strftime("%Y%m%d%H%M%S %z")
    
    def _getLogo(self, channel):
        """Check if there is a logo for the given channel, and (try) to download it if needed"""
        
        # Check that log has not been verified already
        if self._foundLogos.has_key(channel):
            return
        
        # Prepare paths needed for the logo
        if self.logoStore is not None:
            localLogoDir = os.path.join(GRABBERDIR, self.logoStore)
        else:
            localLogoDir = os.path.join(GRABBERDIR, "logos")
        
        logoName = "%s.png" % channel
        localLogo = os.path.join(localLogoDir, logoName)
        remoteLogo = "/tvmenu/images/channels/%s.png" % channel
        
        # Check that logo does not already exist
        if os.path.isfile(localLogo):
            # Found logo, store and return
            self._foundLogos[channel] = localLogo
            return
        
        # Logo not found, try to download it
        try:
            self._epgConnection.request("GET", remoteLogo)
            response = self._epgConnection.getresponse()
            if response.status != 200:
                # Logo cannot be found, set to ignore it
                self._foundLogos[channel] = None
                response.read() # Force response buffer to be emptied
                response.close()
                return
            
        except (socket.error, httplib.CannotSendRequest, httplib.BadStatusLine):
            # Error in connection. Close existing connection.
            self._epgConnection.close()
            
            # Wait for network to recover
            time.sleep(10)
            
            # Reconnect to server and retry
            try:
                self._epgConnection = httplib.HTTPConnection(self.epgServer)
                self._epgConnection.request("GET", remoteLogo)
                response = self._epgConnection.getresponse()
                if response.status != 200:
                    # Logo cannot be found, set to ignore it
                    self._foundLogos[channel] = None
                    response.read() # Force response buffer to be emptied
                    response.close()
                    return
                
            except (socket.error, httplib.CannotSendRequest, httplib.BadStatusLine):
                # Connection remains broken, return (error will be handled in grabEpg function)
                self._foundLogos[channel] = None
                return
        
        # Logo downloaded, store to disk
        try:
            if not os.path.isdir(localLogoDir):
                os.makedirs(localLogoDir)
            
            with open(localLogo, "wb") as logoFile:
                logoFile.write(response.read())
            
            response.close()
            self._foundLogos[channel] = localLogo
        
        except EnvironmentError:
            # Could not store logo, set to ignore it
            self._foundLogos[channel] = None


def main():
    """
    Main entry point of program.
    This function will read the configuration file and start the grabber.
    """
    print "AminoEPGGrabber %s started on %s." % (VERSION, datetime.now())
    
    # Create grabber class
    grabber = AminoEPGGrabber()
    
    # Try to load config file, if it exists
    configFile = os.path.join(GRABBERDIR, "config.xml")
    if os.path.isfile(configFile):
        grabber.loadConfig(configFile)
    
    # Load saved database
    grabber.loadDatabase()
    
    # Grab EPG from IPTV network
    grabber.grabEpg()
    
    # Write database
    grabber.writeDatabase()
    
    # Write XMLTV file
    grabber.writeXmltv()
    
    print "AminoEPGGrabber finished on %s." % datetime.now()

if __name__ == "__main__":
    main()

