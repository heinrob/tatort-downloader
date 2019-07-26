#!/usr/bin/env python3


from lxml import html
from itertools import chain
import requests
import subprocess
import re
import os.path as path
from os import walk
import argparse
import sqlite3
from datetime import datetime
import unicodedata
import shlex

# shortening months for uniform printing
months = (('Januar','Jan.'),('Februar','Feb.'),('März','Mär.'),('April','Apr.'),('Mai','Mai '),('Juni','Jun.'),('Juli','Jul.'),('August','Aug.'),('September','Sep.'),('Oktober','Okt.'),('November','Nov.'),('Dezember','Dez.'))

# remove all special characters for simpler searching as wiki and upload page differ in naming
def normalize(string):
    return re.sub(' +',' ',unicodedata.normalize('NFKD', string).encode("ascii","ignore").decode().replace("'","").replace("-",""))

class Downloader:

    def __init__(self):
        
        parser = argparse.ArgumentParser(description="Download helper for the latest episodes of 'Tatort'.")
        parser.add_argument("-f", "--format", default="mp4", help="video format, default: mp4 (possible formats: see 'man youtube-dl')")
        parser.add_argument("-o", "--output-folder", metavar='FOLDER', default="./", help="destination for the downloaded videos")
        parser.add_argument("-I", "--non-interactive", action='store_true', help="start automatic mode")
        parser.add_argument("-L", "--disable-logging", action='store_true', help="don't log the downloaded episodes")
        parser.add_argument("-r", "--range", default="0-", help="define range to download (a-|-z), automatically sets non-interactive flag")
        parser.add_argument("-p", "--play", action='store_true')
        parser.add_argument("-u", "--user", default="robin", help="define user for watch statistics")
        parser.add_argument("-X", "--dummy", action='store_true', default=False) # only touch files, does not download them
        parser.add_argument("-P", "--player", metavar='PLAYER', default="mpv --fs", help="video player used, default: mpv")
        self.args = vars(parser.parse_args())

        # database init
        if not self.args['disable_logging']:
            self.db = sqlite3.connect("".join((self.args['output_folder'],'tatort.db')))
            self.cursor = self.db.cursor()

        # set user id depending on cl-argument
        self.uid = -1
        if self.args['user']:
            self.cursor.execute("SELECT id FROM users WHERE name=?", (self.args['user'],))
            self.uid = self.cursor.fetchone()[0]

        self.print("                                               \n"
                 + "  ,--.            ,--.                  ,--.   \n"
                 + ",-'  '-. ,--,--.,-'  '-. ,---. ,--.--.,-'  '-. \n"
                 + "'-.  .-'' ,-.  |'-.  .-'| .-. ||  .--''-.  .-' \n"
                 + "  |  |  \\ '-'  |  |  |  ' '-' '|  |     |  |   \n"
                 + "  `--'   `--`--'  `--'   `---' `--'     `--'   \n"
                 + "\n")
    
        # download the newest version of the wiki

        # play mode
        if self.args['play']:
            rows = []
            longest_title = 5 # variable width of title column
            self.cursor.execute("SELECT * FROM downloads ORDER BY id")
            for result in self.cursor.fetchall():
                w = ""
                if str(self.uid) in result[-1].split(","):
                    w = "*"
                longest_title = max(longest_title,len(result[1]))
                rows.append((w,*result))
            condition = ''
            while True:
                self.print(" ID   | S | Premiere      | {:{wid}s} | Ermittler".format('Titel',wid=longest_title))
                self.print(" ---- | - | ------------- | {:-<{wid}s} | ------------------------------".format('',wid=longest_title))
                for row in rows:
                    match = sum([1 for r in row if condition in str(r).lower()]) > 0 # search every column
                    if condition == '' or match:
                        self.print(" {1:>4d} | {0:1s} | {3:>13s} | {2:{wid}s} | {4:30s}".format(*row,wid=longest_title))


                num = input("Nummer|?|!> ")
                if len(num) == 0:
                    condition = ''
                    continue
                if num[0] == '?': # search for string
                    condition = num.split(' ',1)[1].lower()
                    print()
                elif num[0] == '!': # mark tatort
                    pass
                else:
                    break
            # format the given number to match filenames
            num_str = "{:04d}".format(int(num))
            for _, _, filenames in walk(self.args['output_folder']):
                for filename in filenames:
                    if num_str in filename: # file found
                        filename = path.join(self.args['output_folder'], filename)
                        try:
                            args = shlex.split(self.args['player'])
                            args.append(filename)
                            subprocess.run(args, check=True)
                            self.cursor.execute("UPDATE downloads SET watched_by=watched_by||? WHERE id=?",
                                                ("," + str(self.uid), num))
                            self.db.commit()
                            self.db.close()
                        except subprocess.CalledProcessError as error:
                            self.print("The video player reported an error:")
                            self.print(error.stderr)
                            while True:
                                a = input("Still mark video as watched? [y/N]")
                                a.lower()
                                if a == 'y' or a == 'yes':
                                    self.cursor.execute("UPDATE downloads SET watched_by=watched_by||? WHERE id=?",
                                                    ("," + str(self.uid), num))
                                    self.db.commit()
                                    self.db.close()
                                    break
                                elif a == 'n' or a == 'no' or a == '':
                                    break
                                else:
                                    self.print('Please respond with yes or no:')
                        break
                else:
                    self.print(filenames)
                    self.print("No Tatort with this number.")
            return


        # download mode
        # grab the webpages
        page = requests.get("http://www.daserste.de/unterhaltung/krimi/tatort/videos/index.html")
        tree = html.fromstring(page.content)
        titles = tree.xpath('//h4[@class="headline"]/a/text()')
        links = tree.xpath('//h4[@class="headline"]/a/@href')

        wikipage = requests.get("https://de.wikipedia.org/wiki/Liste_der_Tatort-Folgen")
        wikitree_normalized = html.fromstring(normalize(wikipage.content.decode()))
        wikitree = html.fromstring(wikipage.content.decode())

        # links from daserste.de don't contain the domain
        prefix = "http://www.daserste.de"

        self.filenames = []
        self.rows = []
        to_download = []
        dataset = []
        longest_title = 5


        for c, title in enumerate(titles):
            status = ""
            title_origin = title.replace('Tatort: ', '')
            title = normalize(title_origin)
            try:
                # extract further information from wikipedia, if possible
                #TODO: find multiple numbers if existent
                number = wikitree_normalized.xpath('//td/a[text()="' + title + '"]/../../td[1]/text()')[0].replace("\n", "")
            except Exception:# TODO: non_interactive mode
                number = input("Could not find Tatort ID for " + title_origin + ". Please insert> ")
                print("\033[1A")
            
            date = wikitree.xpath('//tr[td[normalize-space()="' + number + '"]]/td[4]/text()')[0].replace("\n", "")
            for mon in months:
                date = date.replace(mon[0],mon[1])
            kommissare = wikitree.xpath('//tr[td[normalize-space()="' + number + '"]]/td[5]/a/text()')[0].replace("\n", "")
            if not self.args['disable_logging']:
                self.cursor.execute("SELECT COUNT(*),* FROM downloads WHERE id=?", (number,))
                if self.cursor.fetchone()[0] == 1:
                    status = "D"

            if status == "":
                to_download.append(c)
            self.rows.append([number, title_origin, date, kommissare])
            dataset.append((c, status, number, date, title_origin, kommissare))
            longest_title = max(longest_title,len(title_origin))

            # delete all special characters in the title
            title = title.replace(" ", "_")

            # create beautiful filename
            number = "{:04d}".format(int(number))
            self.filenames.append("".join((self.args['output_folder'], number, '-', title, '.', self.args['format'])))

        self.print("#  | S | ID   | Premiere      | {:{wid}s} | Ermittler".format('Titel',wid=longest_title))
        self.print("-- | - | ---- | ------------- | {:-<{wid}s} | ------------------------------".format('',wid=longest_title))
        for row in dataset:
            self.print("{:2d} | {:1s} | {:>4s} | {:>13s} | {:{wid}s} | {:30s}".format(*row,wid=longest_title))


        if self.args['non_interactive'] or self.args['range'] != "0-":
            interval = self.build_interval(self.args['range'])
            ids = []
            for c, r in enumerate(self.rows):
                if int(r[0]) in interval and c in to_download:
                    ids.append(c)
        else:
            # ask user for the desired episodes, possible formats: csv, ranges with '-'
            ids = input("Choose [a,b-d,...]> ")
            ids = ids.replace(" ", ",").replace(",,", ",")
            ids = self.expand_numbers(ids)

        # the user typed something wrong
        if ids == -1:
            return

        # strip the user input to the possible IDs
        ids = [x for x in range(len(titles)) if x in ids]
        for i in ids:
            # only download if not existent
            if not path.isfile(self.filenames[int(i)]):
                try:
                    self.print("")
                    if self.args['dummy']:
                        subprocess.run(["touch", self.filenames[int(i)]], check=True)
                    else:
                        subprocess.run(["youtube-dl", "-f", self.args['format'], "-o", self.filenames[int(i)], prefix + links[int(i)]], check=True)
                    # log
                    if not self.args['disable_logging']:
                        self.cursor.execute("INSERT INTO downloads VALUES (?,?,?,?,'')",self.rows[i])
                        self.db.commit()
                except subprocess.CalledProcessError as cpe:
                    self.print("youtube-dl exited with" + cpe.returncode + "\noutput:" + cpe.output,True)
        if not self.args['disable_logging']:
            self.db.close()

    # expand c-f to range(c,f) and single items a to [a]
    def expand_ranges(self,num):
        pieces = num.split("-")
        try:
            if len(pieces) == 1:
                return [int(pieces[0])]
            if pieces[0] == '':
                return range(0,int(pieces[1])+1)
            if pieces[1] == '':
                return range(int(pieces[0]),20)
            return range(int(pieces[0]),int(pieces[1])+1)
        except ValueError:
            return [-1]


    # split the user input at comma and send the args to expand_ranges
    def expand_numbers(self,num):
        try:
            return {x for x in set(chain(*map(self.expand_ranges,num.split(",")))) if x != -1}
        except TypeError: # the user typed tomething wrong
            return -1

    def build_interval(self,num):
        pos = num.find("-")
        num = num.replace("-", "")
        if pos == -1 or num == "":
            self.print("\nERROR: invalid range (" + num + ")",True)
            return [-1]
        if pos == 0:
            self.print("\nDownloading range [0 - {}]".format(num))
            return range(0, int(num))
        self.print("\nDownloading range [{} - INF]".format(num))
        return range(int(num), 20)

    def print(self,message,log=False):
        if log:
            # log to file
            message = message.split("\n")
            time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
            with open(path.join(self.args['output_folder'], "log.txt"), "a") as logfile:
                logfile.write(time + ": " + message[0] + "\n")
                if len(message) > 1:
                    for m in message[1:]:
                        logfile.write("{0:{width}}  {1}\n".format("",m,width=len(time)))
        if not self.args['non_interactive'] or not self.args['disable_logging']:
            print(message)

if __name__ == '__main__':
    Downloader()

