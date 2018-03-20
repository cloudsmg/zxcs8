import requests
from bs4 import BeautifulSoup
import re
import os
import time
import json
import zhconv
from collections import namedtuple
import gevent
from gevent import monkey
from shutil import copyfileobj
import logging


logger = logging.getLogger('zxcs8')
myrule = ['A>E', 'A+B>D+E', 'A-E>A/2']
last_retrieve = time.time()
headers = {'User-Agent': ('User-Agent:Mozilla/5.0 (Macintosh;'
                          ' Intel Mac OS X 10_12_3)'
                          ' AppleWebKit/537.36 (KHTML, like Gecko)'
                          ' Chrome/56.0.2924.87 Safari/537.36')}


monkey.patch_all()


class Book(dict):
    '''Book is a dictionary that stores information of book.'''

    def __init__(self, info):
        '''Create a new Book instance

        Args:
            info(dict): A dict contains book information
        '''
        self['name'] = info.get('name')  # book name
        self['author'] = info.get('author')  # Author
        self['intro'] = info.get('intro')  # Introduction
        self['score1'] = info.get('score1')  # 仙草 excellent
        self['score2'] = info.get('score2')  # 粮草 good
        self['score3'] = info.get('score3')  # 干草 fair
        self['score4'] = info.get('score4')  # 枯草 poor
        self['score5'] = info.get('score5')  # 毒草 bad
        self['size'] = info.get('size')  # compressed file size
        self['url'] = info.get('url')  # website page of the book
        self['dllink'] = info.get('dllink')  # download page of the book

    def download(self):
        '''Download the book.

        The file will be in 'download' folder under current working directory.

        Returns:
            return if exception occured.

        '''
        try:
            g = requests.get(self['dllink'], headers=headers)
        except Exception:
            logger.exception("Cannot open download page: " + self['url'])
        else:
            if not g.ok:
                logger.error(str(g.status_code) + 'error: ' + self['url'])
                return
            else:
                dlsoup = BeautifulSoup(g.text)
                spans = [x.a for x in dlsoup.find_all('span')]
                filelinks = [y.get('href') for y in spans if y]

        for i in filelinks:
            dl = requests.get(i, stream=True, headers=headers)
            filename_extension = re.search('\d/.*?(\..*)', i)[1]
            if dl.ok:
                break
            elif i == filelinks[-1]:
                logger.error('Unable to download: ' + self['name'])
                return

        # Create 'download' folder under current working directory
        if not os.path.isdir('./download/'):
            os.makedirs('./download/')
        with open('./download/' + self['name'] +
                  filename_extension, 'wb') as f:
            copyfileobj(dl.raw, f)
        logger.info("Book '" + self['name'] + "' download completed")

    def to_json(self):
        '''Generate JSON of the book.

        Returns:
            str: The return JSON string
        '''
        return json.dumps(self)

    def check_rules(self, rules):
        '''check the filter of book scores'''
        passed = True
        A = int(self['score1'])
        B = int(self['score2'])
        C = int(self['score3'])
        D = int(self['score4'])
        E = int(self['score5'])
        while passed:
            try:
                for rule in rules:
                    passed = passed and eval(rule)
                break
            except Exception:
                logger.exception("Can't apply filter!")
                return False
        return passed


class Shelf:
    '''
    A set of books with same categories or search result.
    Books are stored in self.content.
    '''

    def __init__(self, url='', name='', shelftype='category'):
        self.url = url
        self.name = name
        self.content = {}
        self.book_links = []
        self.failed_page = []
        self._shelftype = shelftype
        self.download_count = 0
        if url and self._shelftype == 'category':
            self.pages = self.url + '/page/'
        elif url and self._shelftype == 'search':
            self.pages = self.url + '&page='
        else:
            self.pages = ''

    def add_book(self, book):
        if book['name'] not in self.content:
            self.content[book['name']] = book
            logger.info("Book %s added to Shelf %s" %
                        (book['name'], self.name))

    def delete_book(self, book):
        if book['name'] in self.content:
            del self.content[book['name']]
            logger.info("Book %s deleted from Shelf %s" %
                        (book['name'], self.name))
        else:
            logger.info("Deletion failed: Book %s not in Shelf %s" %
                        (book['name'], self.name))
            print(book['name'] + ' is not in the shelf')

    def _get_book_link(self, page):
        currect_page = self.pages + str(page)
        check_sleep_time()
        retry = 3

        while retry:
            try:
                c = requests.get(currect_page, headers=headers)
            except requests.exceptions.ConnectionError:
                logger.exception(('ConnectionError on %s. '
                                  'Retrying in 1 minute. Retries left: %d'
                                  % (currect_page, retry)))
                time.sleep(60)
                retry -= 1
            except requests.exceptions.ConnectTimeout:
                retry -= 1
                logger.exception('ConnectTimeout on %s. Retrying in 3 seconds.'
                                 ' Retries left: %d' % (currect_page, retry))
                if retry != 0:
                    time.sleep(3)
                else:
                    logger.error(('Unable to get book links from %s'
                                  ': ConnectTimeout' % currect_page))
                    return None
                continue
            break

        if not c.ok:
            self.failed_page.append(currect_page)
            logger.error('Unable to get book links of %s: %d error' %
                         (currect_page, c.status_code))
        else:
            global last_retrieve
            last_retrieve = time.time()
            soup2 = BeautifulSoup(c.text)
            all_dt = soup2.find_all('dt')
            for booklink in all_dt:
                self.book_links.append(booklink.a.get('href'))
            logger.info('Successfully get book links from ' + currect_page)

    def get_book_links(self):
        # retrieve all book links from the shelf
        retry = 3
        check_sleep_time()
        while retry:
            try:
                r = requests.get(self.url, headers=headers, timeout=30)
            except requests.exceptions.ConnectionError:
                retry -= 1
                if retry != 0:
                    logger.exception(('ConnectionError on %s. '
                                      'Retrying in 1 minute. Retries left: %d'
                                      % (self.url, retry)))
                    time.sleep(60)
                    continue
                else:
                    logger.error(('Unable to get book links from %s'
                                  ': ConnectionError' % self.url))
                    return None
            except requests.exceptions.ConnectTimeout:
                retry -= 1
                if retry != 0:
                    logger.exception(('ConnectTimeout on %s. '
                                      'Retrying in 3 seconds. '
                                      'Retries left: %d' % (self.url, retry)))
                    time.sleep(3)
                    continue
                else:
                    logger.error(('Unable to get book links from %s'
                                  ': ConnectTimeout' % self.url))
                    return None
            break

        global last_retrieve
        last_retrieve = time.time()

        if not r.ok:
            logger.error(str(r.status_code) + 'error: ' + self['url'])
        else:
            soup = BeautifulSoup(r.text)
            pages = soup.find(id='pagenavi')
            if pages.contents:
                last_page = [i for i in pages.contents if i != ' ']
                last_page = last_page[-1].get('href')
                last_page_num = int(re.search('page.(\d+)',
                                              last_page)[1])
            else:
                last_page_num = 1
            jobs = ([gevent.spawn(self._get_book_link, page)
                     for page in range(1, last_page_num + 1)])
            for i in range(0, len(jobs), 5):
                gevent.joinall(jobs[i:i + 5])
                gevent.sleep(3)
                time.sleep(5)
            logger.info("All %d book links of Shelf %s added" %
                        (len(self.book_links), self.name))

    def get_book_num(self):
        return len(self.content)

    def _create_book_from_link(self, i):
        info = get_book_info(self.book_links[i])
        if not info:
            self.failed_page.append(self.book_links[i])
            logger.error("Unable to create book from %s" % self.book_links[i])
        else:
            tb = create_book(info)
            logger.info('Book %s created from %s' %
                        (self.book_links[i], tb['name']))
            self.add_book(tb)
            gevent.sleep(3)

    def add_all_book(self):
        # create every book from links and add to the shelf then clear links
        jobs = ([gevent.spawn(self._create_book_from_link, i)
                 for i in range(len(self.book_links))])
        for i in range(0, len(jobs), 5):
            time.sleep(3)
            gevent.joinall(jobs[i:i + 5])
        logger.info('All %d books added to Shelf %s' %
                    (len(self.content), self.name))
        self.book_links.clear()

    def _download_by_rule(self, book):
        if book.check_rules(myrule):
            book.download()
            self.download_count += 1
        else:
            logger.info("%s doesnot meet the rule" % book['name'])

    def download_all_by_rule(self):
        jobs = ([gevent.spawn(self._download_by_rule, book[1])
                 for book in self.content.items()])
        gevent.joinall(jobs)
        logger.info('Successfully downloaded %d books from Shelf %s' %
                    (self.name, self.download_count))

    def to_json(self):
        return json.dumps(self, default=lambda o: o.__dict__,
                          sort_keys=True, indent=4)


def search(text):
    # Search by text and return a shelf
    search_url = 'http://www.zxcs8.com/index.php?keyword='
    search_text = convert_to_zhcn(text)
    search_page = search_url + search_text
    name = '搜索 "%s" 的结果' % text

    check_sleep_time()
    try:
        s = requests.get(search_page, headers=headers)
    except Exception as e:
        raise e

    soup5 = BeautifulSoup(s.text)
    if soup5.find(class_='none'):
        print('Sorry, no results matching your criteria were found!')
        logger.warning("No search result of '%s'" % text)
        return None
    else:
        return Shelf(search_page, name, 'search')
        logger.info("Create Shelf of %s" % name)


def get_book_info(page_url):
    # retrieve the information of the book
    result = {}

    if 'zxcs' not in page_url:
        logger.error("Invalid book url:%s" % page_url)
        return result
    result['url'] = page_url
    book_score = ('http://www.zxcs8.com/content/plugins/'
                  'cgz_xinqing/cgz_xinqing_action.php?action=show&id=')
    book_id = re.search('post/(\d*)', page_url).groups()[0]
    retry = 5
    check_sleep_time()

    while retry:
        try:
            r = requests.get(page_url, timeout=30, headers=headers)
        except requests.exceptions.ConnectionError:
            logger.exception(('ConnectionError on %s. '
                              'Retrying in 1 minute. Retries left: %d'
                              % (page_url, retry)))
            time.sleep(60)
            retry -= 1
        except requests.exceptions.ConnectTimeout:
            retry -= 1
            logger.exception('ConnectTimeout on %s. Retrying in 3 seconds.'
                             ' Retries left: %d' % (page_url, retry))
            if retry != 0:
                time.sleep(3)
            else:
                logger.error(('Unable to retrieve book info of %s'
                              ': ConnectTimeout' % page_url))
                return None
            continue
        break
    global last_retrieve
    last_retrieve = time.time()

    soup4 = BeautifulSoup(r.text)
    id_content = soup4.find('div', id='content')
    title = re.search('(.*?)作者：(.*)', id_content.h1.text)
    result['name'] = title.group(1)
    result['author'] = title.group(2)

    tag_p = soup4.find_all('p')
    for p in tag_p:
        temp_text = re.search('【TX', p.text)
        if temp_text:
            temp_text = temp_text.string.replace('\u3000', '')
            break
    res = re.search('【TXT大小】：(.*?)【内容简介】：(.*)', temp_text, flags=re.S)
    result['size'], result['intro'] = res.group(1), res.group(2)
    result['dllink'] = soup4.find(class_='down_2').a.get('href')

    check_sleep_time()
    scores = requests.get(book_score + book_id, headers=headers).text
    scores = scores.split(',')
    result['score1'] = scores[0]
    result['score2'] = scores[1]
    result['score3'] = scores[2]
    result['score4'] = scores[3]
    result['score5'] = scores[4]

    last_retrieve = time.time()

    logger.info("Successfully retrieved info of %s" % page_url)
    return result


def check_sleep_time():
    global last_retrieve
    if time.time() - last_retrieve < 2:
        time.sleep(2)


def create_book(info):
    return Book(info)


def convert_to_zhtw(word):
    # Convert string to traditional Chinese
    return zhconv.convert(word, 'zh-tw')


def convert_to_zhcn(word):
    # Convert string to simplified Chinese
    return zhconv.convert(word, 'zh-cn')


def from_json(json_object):
    # Read json object and convert to Book or Shelf
    if 'content' not in json_object and 'author' in json_object:
        return Book(json.loads(json_object))
    elif 'book_links' in json_object:
        pat = '(.*?)("content": {)(.*?)("failed_page".*)'
        re_result = re.findall(pat, json_object, flags=re.S)[0]
        no_content = re_result[0] + re_result[3]
        books = re.findall('{.*?}', re_result[2], flags=re.S)
        shelf_info = json.loads(no_content, object_hook=lambda d: namedtuple
                                ('temp_class', d.keys())(*d.values()))
        temp_shelf = Shelf(shelf_info.url, shelf_info.name)
        temp_shelf.book_links = shelf_info.book_links
        temp_shelf.failed_page = shelf_info.failed_page

        for book in books:
            print(book)
            temp_shelf.add_book(from_json(book))
        return temp_shelf
    else:
        return 'Unrecognizable JSON object!'


def main():
    logger.setLevel(logging.INFO)
    logger.addHandler(logging.FileHandler('mylog.log', encoding='UTF-8'))
    sh = logging.StreamHandler()
    sh.setLevel(logging.INFO)
    logger.addHandler(sh)
    logger.info("start logging")
    myrule = ['A>1']
    test = 'http://www.zxcs8.com/tag/%E9%BB%91%E6%9A%97%E5%B9%BB%E6%83%B3'
    s1 = Shelf(test, 'test')
    s1.get_book_links()
    s1.add_all_book()


    logger.info('stop logging')


if __name__ == '__main__':
    main()
