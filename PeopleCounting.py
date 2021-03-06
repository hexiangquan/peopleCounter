import numpy as np
import cv2
import time
from datetime import datetime
import math
from tracking import Tracking
from tracking import Blob
from ConfigParser import SafeConfigParser
from utilities import readBuffer, getFrame, getBlobRatio
from bufferedVideoReader import BufVideoReader
from threading import Thread
import Queue
import json
import requests
import pdb

useVideo = False 
useRTSP = True

configfile = '/opt/wikkit/configuration/tk1_config.ini'
uploadURL = "http://120.76.26.101:8000/tk1/return_customer/h_count" 
# from communication.client import post_msg

class Parameters(object):
    def __init__(self):
        """parameters from parameters.ini"""
        parser = SafeConfigParser()
        parser.read(configfile)
        self.mog2History = parser.getint('PeopleCounting', 'mog2History')
        self.mog2VarThrsh = parser.getint('PeopleCounting', 'mog2VarThrsh')
        self.mog2Shadow = parser.getboolean('PeopleCounting', 'mog2Shadow')
        self.mog2LearningRate = parser.getfloat('PeopleCounting', 'mog2LearningRate')
        self.kernelSize = parser.getint('PeopleCounting', 'kernelSize')
        self.scale = parser.getfloat('PeopleCounting', 'scale')
        self.areaThreshold = math.pi * parser.getfloat('PeopleCounting', 'areaRadius')**2
        self.peopleBlobSize = parser.getint('PeopleCounting', 'peopleBlobSize')
        self.distThreshold = parser.getint('PeopleCounting', 'distThreshold')
        self.countingRegion = map(int, parser.get('PeopleCounting', 'countingRegion').split(','))
        self.upperTrackingRegion = map(int, parser.get('PeopleCounting', 'upperTrackingRegion').split(','))
        self.lowerTrackingRegion = map(int, parser.get('PeopleCounting', 'lowerTrackingRegion').split(','))
        self.inactiveThreshold = parser.getint('PeopleCounting', 'inactiveThreshold')
        # self.singlePersonBlobSize = parser.getint('PeopleCounting', 'singlePersonBlobSize')
        self.Debug = parser.getboolean('PeopleCounting', 'Debug')
        self.Visualize = parser.getboolean('PeopleCounting', 'Visualize') or self.Debug
        self.useRatioCriteria = parser.getboolean('PeopleCounting', 'useRatioCriteria')
        self.RTSPurl = parser.get('PeopleCounting','RTSPurl')
        self.RTSPframerate = parser.getint('PeopleCounting','RTSPframerate')

        """ASSUMPTION: ppl entering door walk downards(direction = 1) in the video"""
        self.store_id = parser.getint('store', 'store_id')
        self.camera_id = parser.getint('store', 'camera_id')
        self.ipc_username = parser.get('store', 'ipc_username')
        self.ipc_password = parser.get('store', 'ipc_password') 
        self.wl_dev_cam_id = parser.get('store', 'wl_dev_cam_id')

class bkgModel(object):
    def __init__(self,paramObj):
        """ Initialize MOG2, VideoWriter, and tracking """
        # self.fgbg = cv2.BackgroundSubtractorMOG2(paramObj.mog2History, paramObj.mog2VarThrsh, paramObj.mog2Shadow)
        self.fgbg = cv2.BackgroundSubtractorMOG(paramObj.mog2History, paramObj.mog2VarThrsh, paramObj.mog2Shadow)
        self.kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(paramObj.kernelSize,paramObj.kernelSize))

    def getFgmask(self,paramObj,frame):
        fgmask = self.fgbg.apply(frame, paramObj.mog2LearningRate)
        ret, fgmask = cv2.threshold(fgmask, 200, 255, cv2.THRESH_BINARY) # THRESH_BINARY, THRESH_TOZERO
        fgmask = cv2.morphologyEx(fgmask, cv2.MORPH_CLOSE, self.kernel)
        self.fgmask = cv2.morphologyEx(fgmask, cv2.MORPH_OPEN, self.kernel)

    def getContours(self):
        # find blobs
        self.contours, hierarchy = cv2.findContours(self.fgmask.copy(), cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    
    def getBlobs(self,paramObj,countingObj):
        center = None
        self.blobs = []

        for cnt in self.contours:
            if cv2.contourArea(cnt) < paramObj.areaThreshold:
                continue
            ((x, y), radius) = cv2.minEnclosingCircle(cnt)
            l,u,w,h = cv2.boundingRect(cnt)
            peakVal = None
            peakLoc = None
            if paramObj.useRatioCriteria:
                temp = np.zeros_like(fgmask)
                temp[u:u+h,l:l+w] =1
                blobmask = fgmask * temp
                (peakVal, peakLoc) = getBlobRatio(blobmask, paramObj.countingRegion[2], paramObj.countingRegion[3])

            self.blobs.append(Blob((int(x), int(y)), l, l + w, u, u + h, peakVal, peakLoc, countingObj.time))
            if paramObj.Visualize:
                visObj.visualizeBlobs(frame, x, y, radius, center)


class visualize(object):
    def __init__(self,paramObj,output_width,output_height):
        CODE_TYPE = cv2.cv.CV_FOURCC('m','p','4','v')
        self.video = cv2.VideoWriter('output_detection.avi',CODE_TYPE,30,(output_width,output_height*2),1)

    def visualizeBlobs(self, frame, x, y, radius, center):
        cv2.circle(frame, (int(x), int(y)), int(radius), (0, 255, 255), 2)
        # cv2.ellipse(frame,ellipse,(0,255,255),2)
        cv2.circle(frame, (int(x), int(y)), 5, (0, 0, 255), -1)
        font = cv2.FONT_HERSHEY_SIMPLEX
        cv2.putText(frame, str(center), center, font, 1, (0,255,255), 1)

    def visualizeCounting(self, paramObj, countingObj,bkModelObj,frame,nUp,nDown,output_height):
        # Visualize tracking region, counting region and tracks
        cv2.rectangle(frame, (paramObj.countingRegion[0], paramObj.countingRegion[2]), 
                        (paramObj.countingRegion[1], paramObj.countingRegion[3]), (0, 0, 255), 2)
        cv2.rectangle(frame, (paramObj.upperTrackingRegion[0], paramObj.upperTrackingRegion[2]), 
                        (paramObj.upperTrackingRegion[1], paramObj.upperTrackingRegion[3]), (255, 0, 0), 2)
        cv2.rectangle(frame, (paramObj.lowerTrackingRegion[0], paramObj.lowerTrackingRegion[2]), 
                        (paramObj.lowerTrackingRegion[1], paramObj.lowerTrackingRegion[3]), (255, 0, 0), 2)
        cv2.putText(frame, '# UP %s' % countingObj.totalUp, (5, output_height - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,0,255), 2)
        cv2.putText(frame, '# DOWN %s' % countingObj.totalDown, (5, output_height - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,0,255), 2)
        for idxTrack, track in enumerate(countingObj.tracks):
            track.plot(frame)
            # track.printTrack()

        self.maskedFrame = cv2.bitwise_and(frame, frame, mask = bkModelObj.fgmask)
        self.maskedFrame = np.vstack((frame, self.maskedFrame))
        cv2.imshow('frame', self.maskedFrame)
        self.video.write(self.maskedFrame)

        k = cv2.waitKey(10) & 0xff
        # if k == 27:
        #     break

    def release(self,countingObj):
        if useVideo:
            countingObj.cap.release()
        self.video.release()
        cv2.destroyAllWindows()

class RTSPstream(object):
    def __init__(self,paramObj):
        """prepare for RTSP"""
        self.BufFrameQ = Queue.Queue()
        self.TStampQ = Queue.Queue()
        """Spawn a daemon thread for fetching frames to a list"""
        worker = Thread(target=BufVideoReader, args=(paramObj.RTSPurl,  self.BufFrameQ, self.TStampQ, paramObj.RTSPframerate, ))
        worker.setDaemon(True)
        worker.start()
        self.frame = None
        self.waitForFrm()
        print 'initialization222: self.BufFrameQ.empty() = ', self.BufFrameQ.empty()

    def getFrmRTSP(self):
        # loop until get a frame
        while True:
            if not self.BufFrameQ.empty():
                self.frame = self.BufFrameQ.get()
                self.ts = self.TStampQ.get()
                break
            
            else:
                print "Queue is empty, wait %.3f seconds" %(1./paramObj.RTSPframerate)
                time.sleep(1./paramObj.RTSPframerate)

class PeopleCounting(object):
    def __init__(self,paramObj):
        self.countingData = []
        self.tracks = []
        self.totalUp = 0
        self.totalDown = 0
        if useVideo:
            self.cap = cv2.VideoCapture('/Users/Chenge/Desktop/stereo_vision/peopleCounter/data/2016-07-21/3-4mm/192.168.1.145_01_20160721164209992.mp4')
            # self.cap = cv2.VideoCapture('/Users/Chenge/Desktop/stereo_vision/peopleCounter/data/2016-08-04/3.5m/192.168.0.102_01_20160804172448765.mp4')
            # self.cap = cv2.VideoCapture('/Users/Chenge/Downloads/indoor/2.65/192.168.0.102_01_2016081212240476.mp4')
            # self.cap = cv2.VideoCapture('/Users/Chenge/Downloads/indoor/2.65/192.168.0.102_01_2016081212262378.mp4')

            # self.cap = cv2.VideoCapture('/Users/Chenge/Downloads/indoor/3/192.168.0.102_01_20160812122942713.mp4')

            startOffset = 100;
            self.cap.set(cv2.cv.CV_CAP_PROP_POS_FRAMES, startOffset);
            # startOffset = 300
            # self.cap = readBuffer(startOffset, cap)
            self.frameInd = startOffset
            # self.time = self.frameInd
            self.time = time.time()

        elif useRTSP:
            self.RTSPObj = RTSPstream(paramObj)
            self.RTSPObj.getFrmRTSP()
            self.pre_ts = self.RTSPObj.ts ## initialize the timestamp
            self.time = self.RTSPObj.ts

    def getFrame(self):
        if useVideo:
            ret, frame = self.cap.read()
            self.frameInd += 1
            # self.time = self.frameInd  
            self.time = time.time()

        elif useRTSP:
            self.RTSPObj.getFrmRTSP()
            frame = self.RTSPObj.frame
            self.time = self.RTSPObj.ts


        print 'frameInd/timestamp # %s' % self.RTSPObj.ts
        return frame


    def update(self,nUp,nDown):
        self.totalUp += nUp
        self.totalDown += nDown
        print '# UP %s' % self.totalUp
        print '# DOWN %s' % self.totalDown


    def json_update(self,nUp,nDown):
        """write data into json file"""
        # 1 Start End (downward)
        # -1 Start End (upward)
        if nUp!=0 or nDown!=0:
            for track in self.tracks:
                tempData = {
                    'direction' : track.direction, 
                    # 'LifeStart' : datetime.fromtimestamp(track.lifeStart).strftime('%Y-%m-%d_%H:%M:%S.%f'),  
                    # 'LifeEnd' : datetime.fromtimestamp(track.lifeEnd).strftime('%Y-%m-%d_%H:%M:%S.%f'),    
                    'LifeStart' : track.lifeStart,  
                    'LifeEnd' : track.lifeEnd,  
                    }
                self.countingData.append(tempData)

    def json_upload(self, url, headers):
        data = json.dumps(self.countingData)
        try:
            requests.post(url, data=data, headers=headers)
            # clean up the countingData after successful upload
            self.countingData = []

        except Exception, e:
            print "error posting countingData" + str(e)
    


if __name__ == '__main__':
    paramObj = Parameters()
    uploadURLfull = uploadURL + '/' + str(paramObj.wl_dev_cam_id)
    countingObj = PeopleCounting(paramObj)
    trackingObj = Tracking(paramObj.countingRegion, paramObj.upperTrackingRegion, paramObj.lowerTrackingRegion, paramObj.peopleBlobSize, paramObj.useRatioCriteria)
    bkModelObj = bkgModel(paramObj)
    
    frame = countingObj.getFrame()
    output_width = int(frame.shape[1] * paramObj.scale)
    output_height = int(frame.shape[0] * paramObj.scale)
    if paramObj.Visualize:
        visObj = visualize(paramObj,output_width,output_height)

    if useVideo:
        criteria = countingObj.cap.isOpened()
    elif useRTSP:
        criteria = True
    while(criteria):
        start = time.clock()
        frame = countingObj.getFrame()
        frame = cv2.resize(frame, (output_width, output_height), interpolation = cv2.INTER_CUBIC)

        bkModelObj.getFgmask(paramObj,frame)
        bkModelObj.getContours()
        bkModelObj.getBlobs(paramObj,countingObj)

        # tracking
        countingObj.tracks, nUp, nDown = trackingObj.updateAllTrack(bkModelObj.blobs, countingObj.tracks, paramObj.distThreshold, paramObj.inactiveThreshold)
        countingObj.update(nUp,nDown)
        countingObj.json_update(nUp,nDown)

        end = time.clock()
        print('fps: {}'.format(1 / (end - start)))

        if paramObj.Visualize or paramObj.Debug:
            visObj.visualizeCounting(paramObj, countingObj,bkModelObj,frame,nUp,nDown,output_height)

        """Json dump"""
        # send json to server at 00/15/30/45 minutes of the hour
        now = datetime.now()
        if now.minute in [0, 15, 30, 45]:
            countingObj.json_upload(uploadURLfull, headers)

    if paramObj.visualize or paramObj.Debug:
        visObj.release()
