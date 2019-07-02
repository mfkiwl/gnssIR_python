# -*- coding: utf-8 -*-
"""
# This python code reads a snr file (created by one of my RINEX translators) 
# and computes Lomb Scargle Periodograms (LSP) 
# so that a reflector height (RH) can be estimated.
# It currently makes a plot if requested.
# Kristine M. Larson
#
# This is not currently optimized for tide gauges - the RH dot correction 
# is not implemented.

# Please note that you need to set a REFL_CODE environment variable to
# define the location of your input (and output) files
#
# I have set this up so that you can run it in the background (no plots and all
# frequencies from a list of instructions), or just one frequency 
# (or one satellite) and look at the data/periodograms
# 
# 19mar01, added refraction and MJD to output
# 19mar02, added multiple days
# 19mar13, snow (one day only) vs water levels (midnite crossing corrected by using
# the day before)
# 19apr20, changed location of compressed rinex executable
# 19jun28, change result file naming convetion to include snr file type
# toggle for overwriting LSP results (default will be ot overwrite, but
# for cdron jobs, nice not to)
# 
"""
import sys
import os
import numpy as np
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings("ignore")
import cProfile

import gps as g
import argparse
import scipy.interpolate
import scipy.signal
import read_snr_files as snr

# my internal codes for the refraction correction, which are based on
# codes from TU Vienna
import refraction as refr
import datetime

# set an environment variable for where you are keeping your LSP
# instructions and input files 
# CHANGE FOR YOUR MACHINE
# you can also set this in your .bashrc, which is what i am doing now
# os.environ['REFL_CODE'] = '/Users/kristine/Documents/Research'
xdir = os.environ['REFL_CODE']
 
wantCompression = False

# for some applications, allowing tracks that cross midnite is fine (such as snow)
# but for tides, these is illegal. 
allowMidniteCross = False

# eventually we will use something else but this restricts arcs to one hour
# units are in minutes
delTmax = 70
#
# user inputs the observation file information
parser = argparse.ArgumentParser()
# required arguments
parser.add_argument("station", help="station", type=str)
parser.add_argument("year", help="year", type=int)
parser.add_argument("doy", help="doy", type=int)
parser.add_argument("snrEnd", help="snrEnding", type=int)
# these are the addons (not required)
parser.add_argument("-fr", "--onefreq", default=None, type=int, help="try -fr 1 for GPS L1 only, or -fr 101 for Glonass L1")
parser.add_argument("-amp", "--ampl", default=None, type=float, help="try -amp 10 for minimum spectral amplitude")
parser.add_argument("-azim1", "--azim1", default=None, type=int, help="lower limit azimuth")
parser.add_argument("-azim2", "--azim2", default=None, type=int, help="upper limit azimuth")
parser.add_argument("-e1", "--e1", default=None, type=int, help="lower limit elevation angle")
parser.add_argument("-e2", "--e2", default=None, type=int, help="upper limit elevation angle")
parser.add_argument("-h1", "--h1", default=None, type=int, help="lower limit elevation angle")
parser.add_argument("-h2", "--h2", default=None, type=int, help="upper limit elevation angle")
args = parser.parse_args()
#
# rename the user inputs as variables
#
station = args.station
year = args.year
doy= args.doy
snr_type = args.snrEnd
plt_screen = 1 # always have a plot come to screen
#
titles = ['Northeast', 'Southeast', 'Southwest', 'Northwest']
print(titles[0])

# in case you want to analyze multiple days of data


if args.onefreq == None:
    InputFromScreen = False
else:
    InputFromScreen = True

# Setting some defaults
# use the refraction correction
RefractionCorrection = False
irefr = 0

extension = ''

# make directories for the LSP results 
g.result_directories(station,year,extension)

# default will be to overwrite
overwriteResults = True


# You should not use the peak periodogram value unless it is significant. Using a 
# peak to noise value is one way of defining that significance (not the only way).
# I often use 3, but here I am using much less stringent requirement
PkNoise = 2
# this defines the minimum number of points in an arc.  This depends entirely on the sampling
# rate for the receiver, so you should not assume this value is relevant to your case.
minNumPts = 20 



# get the month and day and the modified julian day, 
# currently using fake date since we are not using
# time varying refraction yet
d = g.doy2ymd(year,doy); month = d.month; day = d.day
dmjd, fracS = g.mjd(year,month,day,0,0,0)


# set some reasonable values for LSP. some of these can be overriden
polyV = 4
desiredP = 0.01 # 1 cm precision
ediff = 2
freqs = [1, 20] # default is to do L1 and L2C
pele = [5, 30] # elevation angle limits for removing the polynomial 
Hlimits = [0.5, 10] # LSP limits
elval = [5,25] # elevation angle limits
NReg = [0.5, 6]
# look at four quadrants to get started
azval = [0, 90, 90,180, 180, 270, 270, 360]
reqAmp = [10, 10]
twoDays = False

# if user inputs these, then it overrides the default
if (args.e1 != None):
    elval[0] = args.e1
if (args.e2 != None):
    elval[1] = args.e2
# elevation angle limit values for the Lomb Scargle
e1 = elval[0]; e2 = elval[1]


if (args.h1 != None):
    Hlimits[0] = args.h1
if (args.h2 != None):
    Hlimits[1] = args.h2
# minimum and maximum LSP limits
minH = Hlimits[0]; maxH = Hlimits[1]


# number of azimuth regions from the standard data input file (came out of read_inputs)
naz = int(len(azval)/2)
print('number of azimuth pairs:',naz)
# in case you want to look at a restricted azimuth range from the command line 
setA = 0
if args.azim1 == None:
    azim1 = 0
else:
    setA = 1
    azim1 = args.azim1

if args.azim2 == None:
    azim2 = 360
else:
    azim2 = args.azim2
    setA = setA + 1

if (setA == 2):
    naz = 1
    azval[0] = azim1
    azval[1] = azim2

# this is for when you want to run the code with just a single frequency, i.e. input at the console
# rather than using the input restrictions
if InputFromScreen:
#    reqAmp[0] = 10
    freqs = [args.onefreq] 
    if (args.ampl == None):
        reqAmp[0] = 10
    else:
        reqAmp[0] = args.ampl



# only doing one day at a time for now
twoDays = False

doy_list = [doy]
# for each day in the doy list
for doy in doy_list:
    fname, resultExist = g.LSPresult_name(station,year,doy,extension) 
    if (resultExist):
        print('Results already exist on disk')
# find the observation file name and try to read it
    if (overwriteResults == False) & (resultExist == True):
        allGood = 0
        print('>>>>> The result file exists for this day and you have selected the do not overwrite option')
    else:
        print('go ahead and read the files')
        obsfile,obsfileCmp = g.define_filename(station,year,doy,snr_type)
        obsfile2,obsfile2Cmp = g.define_filename_prevday(station,year,doy,snr_type)
#   define two datasets - one from one day snr file and the other with 24 hours that
#   have three hours from before midnite and first 21 hours on the given day
#
        allGood,sat,ele,azi,t,edot,s1,s2,s5,s6,s7,s8,snrE = snr.read_snr_multiday(obsfile,obsfile2,twoDays)
#   compress it here
        snr.compress_snr_files(wantCompression, obsfile, obsfile2,twoDays) 

#
#   twoDays = True
#   21:00-23:59 day before plus 0-21:00 day of
# comment out for now - need to correct the elevation angles eventually
#   allGoodP,Psat,Pele,Pazi,Pt,Pedot,Ps1,Ps2,Ps5,Ps6,Ps7,Ps8,PsnrE = snr.read_snr_multiday(obsfile,obsfile2,twoDays)
    if (allGood == 1):
        print('successfully read the first SNR file')
        if RefractionCorrection:
            print('<<<<<< apply refraction correction >>>>>>') 
            corrE = refr.corr_el_angles(ele, p,T)
            ele = corrE
#           g.print_file_stats(ele,sat,s1,s2,s5,s6,s7,s8,e1,e2) 
        ct = 0
# good arcs saved to a plain text file, rejected arcs to local file. Open those file names
        fout,frej = g.open_outputfile(station,year,doy,extension) 
# If you want to make a plot

#  main loop
# for a given list of frequencies

        total_arcs = 0
        for f in freqs:
            rj = 0
            gj = 0
            print('**** looking at frequency ', f, ' ReqAmp', reqAmp[ct], ' doy ', doy)
#   get the list of satellites for this frequency
# try moving azimut haround
            for a in range(naz):
                g.open_plot(plt_screen)
                az1 = azval[(a*2)] ; az2 = azval[(a*2 + 1)]
                print('>>>> azimuths', az1, az2)
                satlist = g.find_satlist(f,snrE)
# for a given satellite
                for satNu in satlist:
                    print('>> Sat number ', satNu)
# and azimuth range
# window the data
                    x,y,Nv,cf,UTCtime,avgAzim,avgEdot,Edot2,delT= g.window_data(s1,s2,s5,s6,s7,s8,sat,ele,azi,t,edot,f,az1,az2,e1,e2,satNu,polyV,pele) 
#           this is a kluge for snr files that have non edot values in column 5
                    MJD = g.getMJD(year,month,day, UTCtime)
                    if Nv > minNumPts:
                        maxF, maxAmp, eminObs, emaxObs,riseSet,px,pz= g.strip_compute(x,y,cf,maxH,desiredP,polyV,minH) 
                        nij =   pz[(px > NReg[0]) & (px < NReg[1])]
                        Noise = 0
                        if (len(nij) > 0):
                            Noise = np.mean(nij)
#                    print(len(nij),NReg[0], NReg[1],eminObs,emaxObs,maxAmp/Noise)
#                   I  will write out the Edot2 value, as Edot is not provided in all snr files
#
#  this is the main QC statement
                        iAzim = int(avgAzim)
                        if (delT < delTmax) & (eminObs < (e1 + ediff)) & (emaxObs > (e2 - ediff)) & (maxAmp > reqAmp[ct]) & (maxAmp/Noise > PkNoise):
                            fout.write(" {0:4.0f} {1:3.0f} {2:6.3f} {3:3.0f} {4:6.3f} {5:6.2f} {6:6.2f} {7:6.2f} {8:6.2f} {9:4.0f} {10:3.0f} {11:2.0f} {12:8.5f} {13:6.2f} {14:7.2f} {15:12.6f} {16:1.0f} \n".format(year,doy,maxF,satNu, UTCtime, avgAzim,maxAmp,eminObs,emaxObs,Nv, f,riseSet, Edot2, maxAmp/Noise, delT, MJD,irefr))
                            print('SUCCESS Azimuth {0:.1f}'.format( iAzim))
                            gj +=1
                            g.update_plot(plt_screen,x,y,px,pz)
                        else:
                            print('FAILED QC for Azimuth {0:.1f} '.format( iAzim))
                            g.write_QC_fails(delT,delTmax,eminObs,emaxObs,e1,e2,ediff,maxAmp, Noise,PkNoise,reqAmp[ct])
                            frej.write(" {0:4.0f} {1:3.0f} {2:6.3f} {3:3.0f} {4:6.3f} {5:6.2f} {6:6.2f} {7:6.2f} \
{8:6.2f} {9:4.0f} {10:3.0f} {11:2.0f} {12:8.5f} {13:6.2f} {14:7.2f} {15:12.6f} \n".format(year,doy,maxF,satNu, UTCtime,\
                       avgAzim,maxAmp,eminObs,emaxObs,Nv, f,riseSet, Edot2,maxAmp/Noise,delT, MJD))
                            rj +=1
                plt.subplot(211)
                plt.xlabel('elev Angles (deg)')
                plt.title(titles[a-1] + ' SNR Data')
                plt.subplot(212)
                plt.xlabel('reflector height (m)')
                plt.title('SNR periodogram')
            print('     good arcs:', gj, ' rejected arcs:', rj)
            ct += 1
            total_arcs = gj + total_arcs
            plt.show()
# close the output files
        fout.close() ; frej.close()
# plot to the screen