import cv2
import numpy as np
import pdb



colors = [(0,255,0), (255,0,0), (0,0,255), (0,255,255), (255,0,255), (255,255,0), (0,128,128), (128,0,128), (128,128,0)]

class Blob(object):
    def __init__(self, center, minx, maxx, miny, maxy):
        self.center = center
        self.minx = minx
        self.maxx = maxx
        self.miny = miny
        self.maxy = maxy


class Track(object):
    def __init__(self, direction, color):
        self.centerList = []
        self.lifetime = 0
        self.inactiveCount = 0  #frame number staying inactive
        self.activeCount = 0
        self.direction = direction  ##the blob's location
        self.generalDirection = None
        self.counted = False
        self.color = color
        # historical maximum blob horizontal span
        self.maxblobspan = 0

    def updateTrack(self, blob):
        self.centerList.append(blob.center)
        self.minx = blob.minx
        self.maxx = blob.maxx
        self.miny = blob.miny
        self.maxy = blob.maxy
        self.inactiveCount = 0
        self.activeCount += 1

    def updateBlobSpan(self, blobspan):
        self.maxblobspan = max(self.maxblobspan, blobspan)

    def predictCenter(self):
        return self.centerList[-1]

    def plot(self, img):
        for i in reversed(xrange(len(self.centerList) - 1)):
            cv2.line(img, self.centerList[i + 1], self.centerList[i], self.color)
            cv2.circle(img, self.centerList[i + 1], 2, self.color, -1)

    def printTrack(self):
        for i in reversed(xrange(len(self.centerList) - 1)):
            print self.centerList[i],
        print ' '


    def fitTracklet(self,upperH,lowerH):
        """estimate direction"""
        if ((np.array(self.centerList)[:,1][1:]-np.array(self.centerList)[:,1][:-1])>=0).sum()/float(len(self.centerList))>=0.70:
            peopleDirection = 1 ## downward
        elif ((np.array(self.centerList)[:,1][1:]-np.array(self.centerList)[:,1][:-1])<=0).sum()/float(len(self.centerList))>=0.70:
            peopleDirection = 2 # upward
        elif np.mean(np.array(self.centerList)[:,1][-3:])< lowerH and np.mean(np.array(self.centerList)[:,1][:3])>upperH:
            peopleDirection = 2 # upward
        elif np.mean(np.array(self.centerList)[:,1][:3])< lowerH and np.mean(np.array(self.centerList)[:,1][-3:])>upperH:
            peopleDirection = 1 # downward
        else:
            peopleDirection = 3 # odd cases

        self.generalDirection = peopleDirection
        self.counted = True

class Tracking(object):
    def __init__(self, countingRegion, trackingRegion, peopleBlobSize):
        self.countUpperBound = countingRegion[0]
        self.countLowerBound = countingRegion[0] + countingRegion[2]
        self.countLeftBound = countingRegion[1]
        self.countRightBound = countingRegion[1] + countingRegion[3]
        self.validTrackUpperBound = trackingRegion[0]
        self.validTrackLowerBound = trackingRegion[0] + trackingRegion[2]
        self.validTrackLeftBound = trackingRegion[1]
        self.validTrackRightBound = trackingRegion[1] + trackingRegion[3]
        self.peopleBlobSize = peopleBlobSize
        self.counter = 0

    """updateAllTracks"""
    def updateTrack(self, blobs, tracks, distThreshold, inactiveThreshold):
        # print tracks
        nBlob = len(blobs)
        nTrack = len(tracks)
        distMatrix = np.zeros((nTrack, nBlob))
        blobMark = np.zeros(nBlob) #whether blob is assigned 
        trackMark = np.zeros(nTrack)  #whether tracklet is assigned with a blob in current frm
        for idxBlob, blob in enumerate(blobs):
            for idxTrack, track in enumerate(tracks):
                distMatrix[idxTrack, idxBlob] = self.distBlobTrack(blob, track)

        nAssignedBlob = 0
        for idxBlob, blob in enumerate(blobs):
            minDist = 10000
            minIdxTrack = 0
            closestTrack = None
            # for each blob, find the closest track < distThreshold. 
            # if the track is not picked yet, assign blob to the track
            for idxTrack, track in enumerate(tracks):
                if distMatrix[idxTrack, idxBlob] < minDist:
                    minDist = distMatrix[idxTrack, idxBlob]
                    minIdxTrack = idxTrack
                    closestTrack = track

            if minDist < distThreshold and trackMark[minIdxTrack] == 0:
                # print minDist
                closestTrack.updateTrack(blob)
                # check whether the new blob is within the detect region, for updating blob span
                if self.checkBlobRegion(blob):
                    closestTrack.updateBlobSpan(blob.maxx-blob.minx)
                trackMark[minIdxTrack] = 1
                blobMark[idxBlob] = 1
                nAssignedBlob += 1

        # print 'Assigned blob: %s' % nAssignedBlob

        # for not assigned blob, determine if it is a valid new track
        newTracks = []
        for idxBlob, blob in enumerate(blobs):
            if blobMark[idxBlob] == 1:
                continue
            direction = self.appearRegion(blob)
            if direction != 0:
                newTrack = Track(direction, colors[self.counter % len(colors)])
                newTrack.updateTrack(blob)
                # update blob span if the newTrack's first blob is within the detect region
                if self.checkBlobRegion(blob):
                    newTrack.updateBlobSpan(blob.maxx-blob.minx)
                newTracks.append(newTrack)
                self.counter += 1

        nUp = 0
        nDown = 0
        for idxTrack, track in enumerate(tracks):
            # for not assigned track, increment inactive states, delete if more than inactiveThreshold
            if trackMark[idxTrack] == 0:
                track.activeCount = 0
                track.inactiveCount += 1
                if track.inactiveCount >= inactiveThreshold:
                    trackMark[idxTrack] = 2
            # if track has passed detection region, increment up/down counter, then inactivate track
            else:
                if track.direction == -1 and track.centerList[-1][1] > self.countLowerBound:
                    # nDown += max(1, int((track.maxx - track.minx) / self.peopleBlobSize + 0.5))
                    nDown = max(1, int(track.maxblobspan / self.peopleBlobSize + 0.5))
                    track.direction = 1
                    # track.counted = True
                elif track.direction == 1 and track.centerList[-1][1] < self.countUpperBound:
                    # nUp += max(1, int((track.maxx - track.minx) / self.peopleBlobSize + 0.5))
                    nUp = max(1, int(track.maxblobspan / self.peopleBlobSize + 0.5))
                    track.direction = -1
                    # track.counted = True
            # elif not track.counted:
            #     if (np.min(np.array(track.centerList)[:,1])<= self.validTrackUpperBound) and (np.max(np.array(track.centerList)[:,1])>=self.validTrackLowerBound):
            #         track.fitTracklet(self.validTrackUpperBound,self.validTrackLowerBound)
            #         if track.generalDirection==1:
            #             nDown += 1
            #         elif track.generalDirection==2:
            #             nUp += 1

        tracks = [track for idx, track in enumerate(tracks) if trackMark[idx] <= 1]
        # append new tracks to track list
        tracks.extend(newTracks)
        return (tracks, nUp, nDown)

    def distBlobTrack(self, blob, track):
        predictCenter = track.predictCenter()
        dist = np.linalg.norm(np.array(blob.center) - np.array(predictCenter))
        # print blob.center, predictCenter, dist
        return dist

    def checkBlobRegion(self, blob):
        """check whether a blob center is within the detect region"""
        if blob.center[0] > self.validTrackLeftBound and blob.center[0] < self.validTrackRightBound and \
           blob.center[1] > self.validTrackUpperBound and blob.center[1] < self.validTrackLowerBound :
            return True
        else:
            return False

    def appearRegion(self, blob):
        """return non-zero values if within the detection region"""
        if blob.center[1] < self.validTrackUpperBound and \
           blob.center[0] > self.validTrackLeftBound and blob.center[0] < self.validTrackRightBound:
            return -1
        elif blob.center[1] > self.validTrackLowerBound and \
           blob.center[0] > self.validTrackLeftBound and blob.center[0] < self.validTrackRightBound:
            return 1
        else:
            return 0
