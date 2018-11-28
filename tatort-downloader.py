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
        self.args = vars(parser.parse_args())

        # database foo
        if not self.args['disable_logging']:
            self.db = sqlite3.connect("".join((self.args['output_folder'],'tatort.db')))
            self.cursor = self.db.cursor()

        self.uid = -1
        if self.args['user']:
            self.cursor.execute("SELECT id FROM users WHERE name=?", (self.args['user'],))
            self.uid = self.cursor.fetchone()[0]

        if self.args['play']:
            self.print("                                               \n"
                     + "  ,--.            ,--.                  ,--.   \n"
                     + ",-'  '-. ,--,--.,-'  '-. ,---. ,--.--.,-'  '-. \n"
                     + "'-.  .-'' ,-.  |'-.  .-'| .-. ||  .--''-.  .-' \n"
                     + "  |  |  \\ '-'  |  |  |  ' '-' '|  |     |  |   \n"
                     + "  `--'   `--`--'  `--'   `---' `--'     `--'   \n"
                     + "\n")

            self.print(" ID   | S | 1Ausstrahlung | Titel                          | Ermittler")
            self.print(" ---- | - | ------------- | ------------------------------ | ------------------------------")
            
            self.cursor.execute("SELECT * FROM downloads ORDER BY id")
            for result in self.cursor.fetchall():
                w = ""
                if str(self.uid) in result[-1].split(","):
                    w = "*"
                self.print(" {1:>4d} | {0:1s} | {3:>13s} | {2:30s} | {4:30s}".format(w, *result))
            num = int(input("number> "))
            num_str = "{:04d}".format(num)
            for _, _, filename in walk(self.args['output_folder']):
                if num_str in filename:
                    filename = path.join(self.args['output_folder'], filename)
                    subprocess.run(["vlc", "-f", filename], check=True)
                    self.cursor.execute("UPDATE downloads SET watched_by=watched_by||? WHERE id=?", ("," + str(self.uid), num))
                    self.db.commit()
                    self.db.close()
                    break
            else:
                self.print("No Tatort with this number.")
            #filename = subprocess.check_output("ls " + self.args['output_folder'] + " | grep " + num, shell=True, universal_newlines=True)
            #filename = path.join(self.args['output_folder'], filename[:-1])
            return


        self.print("                                               \n"
                 + "  ,--.            ,--.                  ,--.   \n"
                 + ",-'  '-. ,--,--.,-'  '-. ,---. ,--.--.,-'  '-. \n"
                 + "'-.  .-'' ,-.  |'-.  .-'| .-. ||  .--''-.  .-' \n"
                 + "  |  |  \\ '-'  |  |  |  ' '-' '|  |     |  |   \n"
                 + "  `--'   `--`--'  `--'   `---' `--'     `--'   \n"
                 + "\n")
        self.print("#  | S | ID   | 1Ausstrahlung | Titel                          | Ermittler")
        self.print("-- | - | ---- | ------------- | ------------------------------ | ------------------------------")
    

        # grab the webpages
        page = requests.get("http://www.daserste.de/unterhaltung/krimi/tatort/videos/index.html")
        tree = html.fromstring(page.content)
        titles = tree.xpath('//h4[@class="headline"]/a/text()')
        links = tree.xpath('//h4[@class="headline"]/a/@href')

        wikipage = requests.get("https://de.wikipedia.org/wiki/Liste_der_Tatort-Folgen")
        wikitree = html.fromstring(wikipage.content)

        # links from daserste.de don't contain the domain
        prefix = "http://www.daserste.de"

        # prepare the deletion of all special characters in the title
        letters_only = re.compile(r"[\w\-]+")

        self.filenames = []
        self.rows = []
        self.unwatched = []


        for c, title in enumerate(titles):
            status = ""
            title = title.replace('Tatort: ', '')
            title = title.replace('Chateau', 'Château')
            try:
                # extract further information from wikipedia, if possible
                number = wikitree.xpath('//td/a[text()="' + title + '"]/../../td[1]/text()')[0].replace("\n", "")
                date = wikitree.xpath('//td/a[text()="' + title + '"]/../../td[4]/text()')[0].replace("\n", "")
                date = date.replace("Mai", "Mai ") # correct spacing
                kommissare = wikitree.xpath('//td/a[text()="' + title + '"]/../../td[5]/a/text()')[0].replace("\n", "")
                if not self.args['disable_logging']:
                    self.cursor.execute("SELECT COUNT(*),* FROM downloads WHERE id=?", (number,))
                    if self.cursor.fetchone()[0] == 1:
                        status = "D"
            except Exception:
                # beautiful dashes, if not possible
                number = " -- "
                date = "     ---     "
                kommissare = "             ----"
            if status == "":
                self.unwatched.append(c)
            self.rows.append([number, title, date, kommissare])
            
            self.print("{:2d} | {:1s} | {:>4s} | {:>13s} | {:30s} | {:30s}".format(c, status, number, date, title, kommissare))

            # delete all special characters in the title
            title = title.replace(" ", "_")
            title = letters_only.findall(title)[0]

            # create beautiful filename
            number = "{:04d}".format(int(number))
            self.filenames.append("".join((self.args['output_folder'], number, '-', title, '.', self.args['format'])))


        if self.args['non_interactive'] or self.args['range'] != "0-":
            interval = self.build_interval(self.args['range'])
            ids = []
            for c, r in enumerate(self.rows):
                if int(r[0]) in interval and c in self.unwatched:
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
        length = len(pieces)
        if length == 1:
            try:
                return [int(pieces[0])]
            except ValueError:
                return [-1]
        elif length == 2:
            try:
                return range(int(pieces[0]), int(pieces[1])+1)
            except ValueError:
                return [-1]
        else:
            raise IndexError("Too many dashes (-)!")


    # split the user input at comma and send the self.args to expand_ranges
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
        return range(int(num), 10000)

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

