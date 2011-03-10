#/usr/bin/env python

"""
A XMLTV compatible EPG grabber for the Amino EPG.

Supported TV networks:
OnsNetEindhoven
OnsBrabantNet
"""

#EPG downloaden IPTV, een omschrijving
#
#OVERALL EPG:
#http://w.zt6.nl/epgdata/epgdata.<yyyy><mm><dd>.<dagdeel>.json.gz
#Waarbij <dagdeel> 1 of 2 is.
#
#Voorbeeld:
#http://w.zt6.nl/epgdata/epgdata.20110127.1.json.gz
#
#
#Detail EPG:
#http://w.zt6.nl/epgdata/<PIDLD>/<PID>.json
#Waarbij <PID> het programma ID is uit de overall EPG.
#Waarbij <PIDLD> de laatste twee karakters zijn van de <PID>.
#
#Voorbeeld:
#http://w.zt6.nl/epgdata/06/0010030700002206.json

#Program flow-----
#loop: download EPG for each part of day until maxdays reached or no data available
#    Add Channel data to internal XML if not present yet
#    loop: go through downloaded data listing each channel and show
#        Download data for each show, add to internal XML
#Write XML

#Program flow- IMPROVED
#Load existing XML
#Strip obsolete (past) data from XML
#loop: download EPG for each part of day until maxdays reached or no data available
#    Add Channel data to internal XML if not present yet
#    loop: go through downloaded data listing each channel and show
#        Is a show changed or not present yet?
#            YES: Update show in XML
#            Download data for show, add to internal XML
#Write XML

import json
import urllib2
import gzip
import StringIO
import re
from datetime import datetime, date, timedelta
import pytz
import socket
from xml.dom.minidom import Document

# CONFIG, to be loaded dynamically
epgServer = "192.168.0.101:8080"
#epgServer = "w1.zt6.nl"
localIP = "192.168.0.100" # Local IP to bind to, leave empty for default IP
timezone = "Europe/Amsterdam"
maxDays = 1
noDetails = False

#---------------------------------------------------------#
# NOTHING TO CONFIGURE BELOW                              #
#---------------------------------------------------------#

#Set up local timezone
amsterdam = pytz.timezone(timezone)

# Create monkey patch to allow interface binding
def set_bound_socket(sourceIP):
    true_socket = socket.socket
    def bound_socket(*a, **k):
        sock = true_socket(*a, **k)
        sock.bind((sourceIP, 0))
        return sock
    socket.socket = bound_socket

def getNodeText(nodelist):
    """Extract text from XML node"""
    rc = []
    for node in nodelist:
        if node.nodeType == node.TEXT_NODE:
            rc.append(node.data)
    return ''.join(rc)

def processBasicEPGChannels(basicEpg, tvTag, xmltv):
    """
    Add channel details to the xmltv file.
    """
    
    # Convert stored channels to list
    channellist = []
    for channel in tvTag.getElementsByTagName("channel"):
        channellist.append(getNodeText(channel.getElementsByTagName("display-name")[0].childNodes))
    
    # Read basicEpg to get channels and add them to channel list if they are missing
    for channel in basicEpg.keys():
        if channel not in channellist:
            #Channel not in XML yet, add it
            channelTag = xmltv.createElement("channel")
            channelTag.setAttribute("id", channel)
            channelDisplayNameTag = xmltv.createElement("display-name")
            channelDisplayNameTag.setAttribute("lang", "nl")
            channelDisplayNameTagText = xmltv.createTextNode(channel) # For now make the display name equal to the ID
            channelDisplayNameTag.appendChild(channelDisplayNameTagText)
            channelTag.appendChild(channelDisplayNameTag)
            tvTag.appendChild(channelTag)
            
            # Update the internal channel list
            channellist.append(channel)
            

def processBasicEPGPrograms(basicEpg, grabDate, dayPart, tvTag, xmltv):
    """
    Add program details to the xmltv file.
    This function will download the program details if required.
    """
    for channel, programs in basicEpg.iteritems():
        for program in programs:
            # Add every program to the XML file
            
            # Convert timestamps to strings that comply with XMLTV (YYYYMMDDhhmmss)
            startTime = datetime.fromtimestamp(program["start"], amsterdam)
            startTimeTxt = startTime.strftime("%Y%m%d%H%M%S %z")
            stopTime = datetime.fromtimestamp(program["end"], amsterdam)
            stopTimeTxt = stopTime.strftime("%Y%m%d%H%M%S %z")
            
            # Construct programme tag
            programmeTag = xmltv.createElement("programme")
            programmeTag.setAttribute("start", startTimeTxt)
            programmeTag.setAttribute("stop", stopTimeTxt)
            programmeTag.setAttribute("channel", channel)
            tvTag.appendChild(programmeTag)
            
            # Construct title tag
            titleTag = xmltv.createElement("title")
            titleTag.setAttribute("lang", "nl")
            titleTagText = xmltv.createTextNode(program["name"])
            titleTag.appendChild(titleTagText)
            programmeTag.appendChild(titleTag)
            
            # Get detailed information (if available)
            programId =  program["id"]
            programIdGroup = programId[-2:]
            url = "http://" + epgServer + "/epgdata/" + programIdGroup + "/" + programId + ".json"
            
            if noDetails:
                continue
        
            try:
                detailData = urllib2.urlopen(url)
            except urllib2.HTTPError:
                continue # Skip silently to next programme
            
            detailEpg = json.load(detailData, "UTF-8")
            
            # TODO: Strip characters that are not in UTF-8 code page
            # Add data to XML, if applicable
            # Subtitle
            if len(detailEpg["episodeTitle"]) > 0 :
                # Add sub-title tag
                subtitleTag = xmltv.createElement("sub-title")
                subtitleTag.setAttribute("lang", "nl")
                subtitleTagText = xmltv.createTextNode(detailEpg["episodeTitle"])
                subtitleTag.appendChild(subtitleTagText)
                programmeTag.appendChild(subtitleTag)
                
            # Description
            if len(detailEpg["description"]) > 0:
                # Add desc tag
                descriptionTag = xmltv.createElement("desc")
                descriptionTag.setAttribute("lang", "nl")
                descriptionTagText = xmltv.createTextNode(detailEpg["description"])
                descriptionTag.appendChild(descriptionTagText)
                programmeTag.appendChild(descriptionTag)
                
            # Credits
            if len(detailEpg["actors"]) > 0 or len(detailEpg["directors"]) > 0:
                # Add credits tag
                creditsTag = xmltv.createElement("credits")
                for actor in detailEpg["actors"]:
                    actorTag = xmltv.createElement("actor")
                    actorTagText = xmltv.createTextNode(actor)
                    actorTag.appendChild(actorTagText)
                    creditsTag.appendChild(actorTag)
                    
                for director in detailEpg["directors"]:
                    directorTag = xmltv.createElement("director")
                    directorTagText = xmltv.createTextNode(director)
                    directorTag.appendChild(directorTagText)
                    creditsTag.appendChild(directorTag)
                
                programmeTag.appendChild(creditsTag)
            
            # Category's
            if len(detailEpg["genres"]) > 0:
                # Add multiple category tags
                for genre in detailEpg["genres"]:
                    categoryTag = xmltv.createElement("category")
                    categoryTag.setAttribute("lang", "nl")
                    categoryTagText = xmltv.createTextNode(genre)
                    categoryTag.appendChild(categoryTagText)
                    programmeTag.appendChild(categoryTag)


def main():
    # Patch socket if required
    if localIP != "":
        set_bound_socket(localIP)
    
    # Set up XML tree
    xmltv = Document() # create new XML document   
    tvTag = xmltv.createElement("tv")
    tvTag.setAttribute("source-info-url", epgServer)
    tvTag.setAttribute("source-info-name", "Local amino EPG server")
    tvTag.setAttribute("generator-info-name", "AminoEPGGrabber v0.0.1 (C) 2011 Jeroen Bogers")
    tvTag.setAttribute("generator-info-url", "http://gathering.tweakers.net")
    xmltv.appendChild(tvTag)
    
    # Get EPG for every day from now until no more data is available
    for grabDay in range(maxDays):
        for dayPart in range(0, 3):
            grabDate = date.today() + timedelta(days=grabDay)
            print "Grabbing", str(grabDate), "part", dayPart, "(day " + str(grabDay+1) + "/" + str(maxDays) + ")"
        
            # Get basic EPG
            fileId = grabDate.strftime("%Y%m%d.") + str(dayPart)
            url = "http://" + epgServer + "/epgdata/epgdata." + fileId + ".json.gz"
            try:
                epgData = urllib2.urlopen(url)
            except urllib2.HTTPError,e:
                print "HTTP Error", e.code, "(failed on fileid", fileId + ")"
                break # exit loop
            
            # Decompress and retrieve data
            compressedStream = StringIO.StringIO(epgData.read())
            rawData = gzip.GzipFile(fileobj=compressedStream).read()
            basicEpg = json.loads(rawData, "UTF-8")
            
            # Process basic EPG
            processBasicEPGChannels(basicEpg, tvTag, xmltv)
            processBasicEPGPrograms(basicEpg, grabDate, dayPart, tvTag, xmltv)

    # Set up regular expressions to fix XML string
    xml_reformat = re.compile('>\n\s+([^<>\s].*?)\n\s+</', re.DOTALL)
    
    # Fix 'pretty' XML
    prettyXml = xml_reformat.sub('>\g<1></', xmltv.toprettyxml(indent="  ", encoding="UTF-8"))
    
    # Remove unprintable characters
    #prettyXml = illegal_xml_re.sub('', prettyXml)

    # Write XMLTV file to disk
    outFile = open("aminoepg.xml", "w")
    outFile.write(prettyXml)
    
    print "Finished grabbing EPG on " + str(datetime.now())
    
if __name__ == "__main__":
    main()   

    
    
    
    


