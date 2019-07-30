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

# sqlite status format: dwm (downloaded,watched,marked)
STATUS = {'d': '\033[2m-\033[0m', 'w': '\033[32m*\033[0;0m', 'm': '\033[31;1m!\033[0;0m', ' ': ''}

# shortening months for uniform printing
months = (('Januar','Jan.'),('Februar','Feb.'),('März','Mär.'),('April','Apr.'),('Mai','Mai '),('Juni','Jun.'),('Juli','Jul.'),('August','Aug.'),('September','Sep.'),('Oktober','Okt.'),('November','Nov.'),('Dezember','Dez.'))

# remove all special characters for simpler searching as wiki and upload page differ in naming
def normalize(string):
    return re.sub(' +',' ',unicodedata.normalize('NFKD', string).encode("ascii","ignore").decode().replace("'","").replace("-",""))

# ask user for confirmation in a loop
def input_loop(question,answers=(('j','ja',''),('n','nein')),err='Bitte mit ja oder nein antworten'):
    while True:
        a = input(question).lower()
        if a in answers[0]:
            return True
        if a in answers[1]:
            return False
        print(err)

class Status:
    STATUS = {'downloaded': 0b1, 'watched': 0b10, 'marked': 0b100}
    def __init__(self,s):
        try:
            self.status = int(s)
        except ValueError:
            self.status = 0
    def __str__(self):
        return str(self.status)
    def __repr__(self):
        return 'X'
    def __format__(self,fmt):
        if isinstance(fmt,str):
            if self.status & self.STATUS['marked']:
                return '\033[31;1m!\033[0;0m'
            if self.status & self.STATUS['watched']:
                return '\033[32m*\033[0;0m'
            if self.status & self.STATUS['downloaded']:
                return '\033[2m-\033[0m'
            return ' '
        else:
            raise ValueError
    def has(self,s):
        return self.status & self.STATUS[s]
    def toggle(self,s):
        self.status = self.status ^ self.STATUS[s]
        

class Downloader:

    def __init__(self):
        
        parser = argparse.ArgumentParser(description="Download helper for the latest episodes of 'Tatort'.")
        parser.add_argument("-f", "--format", default="mp4", help="video format, default: mp4 (possible formats: see 'man youtube-dl')")
        parser.add_argument("-o", "--output-folder", metavar='FOLDER', default="./", help="destination for the downloaded videos")
        parser.add_argument("-I", "--non-interactive", action='store_true', help="start automatic mode")
        parser.add_argument("-L", "--disable-logging", action='store_true', help="don't log the downloaded episodes")
        parser.add_argument("-r", "--range", default="0-", help="define range to download (a-|-z), automatically sets non-interactive flag")
        parser.add_argument("-p", "--play", action='store_true')
        parser.add_argument("-X", "--dummy", action='store_true', default=False) # only touch files, does not download them
        parser.add_argument("-P", "--player", metavar='PLAYER', default="mpv --fs", help="video player used, default: mpv")
        self.args = vars(parser.parse_args())

        # database init
        if not self.args['disable_logging']:
            self.db = sqlite3.connect("".join((self.args['output_folder'],'tatort.db')))
            self.cursor = self.db.cursor()

        self.print("                                               \n"
                 + "  ,--.            ,--.                  ,--.   \n"
                 + ",-'  '-. ,--,--.,-'  '-. ,---. ,--.--.,-'  '-. \n"
                 + "'-.  .-'' ,-.  |'-.  .-'| .-. ||  .--''-.  .-' \n"
                 + "  |  |  \\ '-'  |  |  |  ' '-' '|  |     |  |   \n"
                 + "  `--'   `--`--'  `--'   `---' `--'     `--'   \n"
                 + "\n")
    


        ### play mode
        if self.args['play']:
            rows = []
            longest_title = 5 # variable width of title column
            self.cursor.execute("SELECT * FROM downloads ORDER BY id")
            for result in self.cursor.fetchall():
                longest_title = max(longest_title,len(result[1]))
                rows.append({'id':result[0],'title':result[1],'date':result[2],'kommissar':result[3],'status':Status(result[4])})
            condition = ''
            silent = False
            while True:
                if not silent:
                    self.print(" ID   | S | Premiere      | {:{wid}s} | Ermittler".format('Titel',wid=longest_title))
                    self.print(" ---- | - | ------------- | {:-<{wid}s} | ------------------------------".format('',wid=longest_title))
                    for row in rows:
                        #pretty_status = str(row['status'])
                        match = sum([1 for r in row.values() if condition in str(r).lower()]) # search every column
                        #match += 1 if condition in pretty_status else 0
                        if condition == '' or match > 0:
                            self.print(" {id:>4d} | {status:1s} | {date:>13s} | {title:{wid}s} | {kommissar:30s}".format(**row,wid=longest_title))
                silent = False

                num = input("Nummer|?|!> ")
                if len(num) == 0:
                    condition = ''
                    continue
                if num[0] == 'h':
                    self.print('h\t- zeige diese Hilfe an')
                    self.print('s|? $\t- suche nach $')
                    self.print('m|! #\t- markiere #')
                    self.print('w #\t- markiere # als gesehen')
                    self.print('q\t- beende das Programm')
                    silent = True
                elif num[0] in ('s','?'): # search for string
                    condition = num.split(' ',1)[1].lower()
                    print()
                elif num[0] in ('m','!'): # mark tatort
                    n = num.split(' ')[1]
                    idx = int(n) - 1
                    # toggle mark in status
                    rows[idx]['status'].toggle('marked')
                    self.cursor.execute("UPDATE downloads SET status=? WHERE id=?",(str(rows[idx]['status']),n))
                    self.db.commit()
                    self.print('Markierung für #{} geändert\n'.format(n))
                    silent = True
                elif num[0] == 'w':
                    silent = True
                    n = num.split(' ')[1]
                    idx = int(n) - 1
                    if not rows[idx]['status'].has('downloaded'):
                        if not rows[idx]['status'].has('watched'):
                            if not input_loop('#{} ist nicht heruntergeladen. Trotzdem gesehen? [j/N]'.format(n),answers=(('j','ja'),('n','nein',''))):
                                continue
                    rows[idx]['status'].toggle('watched')
                    self.cursor.execute("UPDATE downloads SET status=? WHERE id=?",(str(rows[idx]['status']),n))
                    self.db.commit()
                    self.print('Status für #{} geändert\n'.format(n))
                    
                elif num[0] == 'q':
                    exit(0)
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
                        except subprocess.CalledProcessError as error:
                            self.print("The video player reported an error:")
                            self.print(error.stderr)
                        # do not ask for watch marking if already watched
                        #status = [r for r in rows if r['id'] == int(num)][0]['status']
                        idx = int(num) - 1
                        if rows[idx]['status'].has('watched'):
                            break
                        if input_loop("Tatort als gesehen markieren? [J/n]"):
                            rows[idx]['status'].toggle('watched')
                            if rows[idx]['status'].has('marked') and input_loop('Markierung entfernen? [J/n]'):
                                rows[idx]['status'].toggle('marked')
                            self.cursor.execute("UPDATE downloads SET status=? WHERE id=?",(str(rows[idx]['status']),num))
                            self.db.commit()
                            self.db.close()
                        break
                else:
                    self.print(filenames)
                    self.print("Kein Tatort mit dieser Nummer heruntergeladen.")
            return




        ### download mode
        # grab the webpages
        page = requests.get("http://www.daserste.de/unterhaltung/krimi/tatort/videos/index.html")
        tree = html.fromstring(page.content)
        titles = tree.xpath('//h4[@class="headline"]/a/text()')
        links = tree.xpath('//h4[@class="headline"]/a/@href')

        wikipage = requests.get("https://de.wikipedia.org/wiki/Liste_der_Tatort-Folgen")
        wikitree = html.fromstring(wikipage.content.decode())

        # links from daserste.de don't contain the domain
        prefix = "http://www.daserste.de"

        to_download = []
        dataset = []
        longest_title = 5



        ### update the database
        # get all ids currently in database
        self.cursor.execute("SELECT id FROM downloads")
        ids = [x[0] for x in self.cursor.fetchall()]
        # download the newest version of the wiki
        for tablerow in wikitree.xpath('//*[@id="mw-content-text"]/div/table[1]/tbody/tr'):
            episode = [tablerow.getchildren()[i].text_content()[:-1] for i in [0,1,3,4]]
            try:
                episode[0] = int(episode[0])
            except ValueError: # first row is the headline with text
                continue
            # remove newlines, insert missing spaces before '(' and after '/'
            episode[3] = episode[3].replace('\n','')
            episode[3] = re.sub(r'(?<=\S)\(',r' (',episode[3])
            episode[3] = re.sub(r'/(?=\S)',r'/ ',episode[3])
            
            for mon in months: # reformat the dates
                episode[2] = episode[2].replace(mon[0],mon[1])
            if '[' in episode[2]: # remove wikipedias annotations
                episode[2] = episode[2].split('[')[0]
            episode[2] = re.sub(r'(\w*) \(.*',r'\1',episode[2])
            
            episode.append(normalize(episode[1])) # append the searchable title
            # remove hint for double names from main title
            if '(Folge' in episode[1]:
                episode[1] = episode[1].split('(')[0]
            if episode[0] in ids:
                #self.cursor.execute("UPDATE downloads SET title=?,normalized=? WHERE id=?",(episode[1],episode[4],episode[0]))
                continue
            else:
                self.cursor.execute("INSERT INTO downloads VALUES (?,?,?,?,'',?)",episode)
                self.db.commit()
        

        ### download the newest episodes
        for c, title in enumerate(titles):
            title_origin = title.replace('Tatort: ', '')
            # find episode in database based on the name
            title = normalize(title_origin)
            self.cursor.execute("SELECT * FROM downloads WHERE normalized LIKE ?",('%'+title+'%',))
            row = self.cursor.fetchall()
            if len(row) != 1:
                # TODO: non_interactive mode
                for i,r in enumerate(row):
                    # duplicate names
                    if '(Folge' in r[5]:
                        continue
                    # exact match
                    if r[5] == title:
                        row = row[i]
                        break
                else: # if duplicate names, ask user for ID using the teasertext as hint
                    episodepage = requests.get(prefix + links[c])
                    episodetree = html.fromstring(episodepage.content)
                    teasertext = episodetree.xpath('//p[@class="teasertext"][2]/text()')[0].replace('\n','')
                    print(teasertext)
                    number = input("Titel '" + title_origin + "' nicht eindeutig. Bitte Nummer angeben> ")
                    self.cursor.execute("SELECT * FROM downloads WHERE id=?",(int(number),))
                    row = self.cursor.fetchall()[0]
                    self.print("\033[1A") #TODO remove more/less lines
            else:
                row = row[0] 
            status = '-' if Status(row[4]).has('downloaded') else ''
            if status == '':
                to_download.append(c)
            longest_title = max(longest_title,len(title_origin))

            # make title filename friendly
            title = title.replace(" ", "_")
            # create beautiful filename
            number = "{:04d}".format(row[0])
            filename = "".join((self.args['output_folder'], number, '-', title, '.', self.args['format']))
            dataset.append({'count':c, 'status':status, 'id':row[0], 'date':row[2], 'title':title_origin, 'kommissar':row[3], 'file':filename})

        self.print("#  | S | ID   | Premiere      | {:{wid}s} | Ermittler".format('Titel',wid=longest_title))
        self.print("-- | - | ---- | ------------- | {:-<{wid}s} | ------------------------------".format('',wid=longest_title))
        for row in dataset:
            self.print("{count:2d} | {status:1s} | {id:>4d} | {date:>13s} | {title:{wid}s} | {kommissar:30s}".format(**row,wid=longest_title))


        if self.args['non_interactive'] or self.args['range'] != "0-":
            interval = self.build_interval(self.args['range'])
            ids = []
            for c, r in enumerate(dataset):
                if int(r['id']) in interval and c in to_download:
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
            i = int(i)
            # only download if not existent
            if not path.isfile(dataset[i]['file']):
                try:
                    self.print("")
                    if self.args['dummy']:
                        subprocess.run(["touch", dataset[i]['file']], check=True)
                    else:
                        subprocess.run(["youtube-dl", "-f", self.args['format'], "-o", dataset[i]['file'], prefix + links[i]], check=True)
                    self.cursor.execute("UPDATE downloads SET status=status+? WHERE id=?",(Status.STATUS['downloaded'],dataset[i]['id'],))
                    self.db.commit()
                except subprocess.CalledProcessError as cpe:
                    self.print("youtube-dl exited with" + cpe.returncode + "\noutput:" + cpe.output,True)
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
            self.print("\nERROR: ungültiges Intervall (" + num + ")",True)
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

