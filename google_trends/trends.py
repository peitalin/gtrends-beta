#!/usr/bin/env python
# encoding: utf-8

#############################################################
# Google Trends Query Utility
# Author: Dan Garant (dgarant@cs.umass.edu)
# Updated 05/3/14 Peita Lin (peita_lin@hotmail.com)
#
# Can be used with command-line invocation or as a call from another package.
# Non-standard dependencies: argparse, requests, arrow, fuzzywuzzy
#############################################################


from __future__     import print_function, absolute_import
from time           import sleep
import os, sys, csv, random, math
import requests, arrow, argparse

from google_auth    import authenticate_with_google
from google_class   import FormatException, QuotaException, KeywordData
from disambiguate   import disambiguate_keywords, interpolate_ioi, \
                            conform_interest_over_time, change_in_ioi

py3 = sys.version_info[0] == 3
try:
    from IPython import embed
except ImportError("IPython debugging unavailable"):
    pass


DEFAULT_LOGIN_URL = "https://accounts.google.com.au/ServiceLogin"
DEFAULT_AUTH_URL = "https://accounts.{domain}/ServiceLoginAuth"
DEFAULT_TRENDS_URL = "http://www.{domain}/trends/trendsReport"
# okay to leave domain off here since it's a GET request, redirects are no problem
INTEREST_OVER_TIME_HEADER = "Interest over time"
EXPECTED_CONTENT_TYPE = "text/csv; charset=UTF-8"
NOW = arrow.utcnow()




def main():
    """Parses arguments and initiates the trend querying process."""

    help_docs = {
        # Group 1: mutually exclusive arguments
        '--keywords': "A comma-separated list of phrases to query. Replaces --batch-input.",
        '--file': "filepath containing newline-separated trends query terms.",
        '--cik-file': "File with rows [cik|keyword|date]. For firms only.",
        # Group 2: mutually exclusive arguments
        '--all-quarters': "Loops keyword over quarters from a starting date: " \
                        + "--all-quarters 2004-01. This returns daily data if available.",
        '--all-years': "Loops keyword through multiple years from a starting year: " \
                        + "--all-years 2007-01. Usually returns weekly data.", \
        '--ipo-quarters': "Loops keyword through multiple quarters from a " \
                        + "-6 months and +6 months from a specific date",
        # General Arguments
        '--start-date': "Start date for the query in the form yyyy-mm",
        '--end-date': "End date for the query in the form yyyy-mm",
        '--output': "Directory to write CSV files to, otherwise writes results to std out.",
        '--username': "Username of Google account to use when querying trends.",
        '--password': "Password of Google account to use when querying trends.",
        '--login-url': "Address of Google's login service.",
        '--auth-url': "Authenticate URL: Address of Google's login service.",
        '--trends-url': "Address of Google's trends querying URL.",
        '--throttle': "Number of seconds to space out requests, this is to avoid rate limiting.",
        '--category': "Category for queries, e.g 0-7-107 for finance->investing. See categories.txt",
        '--quiet-io': "Does not write entity type to csv file.",
    }


    command_line_args = (
        #[0]flag            [1]arg-name(dest)    [2]default
        # Group 1: mutually exclusive arguments
        ('--keywords',      "keywords",          None),
        ('--file',          "batch_input_path",  None),
        ('--cik-file',      "cik_file",          None),
        # Group 2: mutually exclusive arguments
        ('--all-quarters',  "all_quarters",      None),
        ('--all-years',     "all_years",         None),
        ('--ipo-quarters',  "ipo_quarters",      None),
        ('--start-date',    "start_date",        NOW.replace(months=-2)),
        # General Arguments
        ('--end-date',      "end_date",          NOW),
        ('--output',        "batch_output_path", "terminal"),
        ('--username',      "username",          None),
        ('--password',      "password",          None),
        ('--login-url',     "login_url",         DEFAULT_LOGIN_URL),
        ('--auth-url',      "auth_url",          DEFAULT_AUTH_URL),
        ('--trends-url',    "trends_url",        DEFAULT_TRENDS_URL),
        ('--throttle',      "throttle",          0),
        ('--category',      "category",          None),
        ('--quiet-io',       "quiet_io",         None)
    )

    parser = argparse.ArgumentParser(prog="trends.py")
    # Mutually exclusive arguments
    arg_group1 = parser.add_mutually_exclusive_group()
    arg_group2 = parser.add_mutually_exclusive_group()

    [arg_group1.add_argument(A[0], help=help_docs[A[0]], dest=A[1], default=A[2])
        for A in command_line_args[:3]]

    [arg_group2.add_argument(A[0], help=help_docs[A[0]], dest=A[1], default=A[2])
        for A in command_line_args[3:7]]

    # General Arguments
    [parser.add_argument(A[0], help=help_docs[A[0]], dest=A[1], default=A[2])
        for A in command_line_args[7:]]


    def missing_args(args):
        "Make sure essential arguments are supplied."
        if not (args.password or args.username):
            sys.stderr.write("ERROR: Use --username and --password flags.\n")
            sys.exit(5)
        elif not (args.keywords or args.batch_input_path or args.cik_file):
            sys.stderr.write("ERROR: Use --keywords or --file, try --help for details.\n")
            sys.exit(5)
        elif args.ipo_quarters and not args.start_date and not args.end_date:
            sys.stderr.write("ERROR: --ipo_quarters requires a filing-date." +
                " Try: --ipo_quarters 2012-01 (day insensitive)")
        if args.cik_file and (args.start_date == NOW):
            print('Mixing --cik-file and --start-date, ignoring --start-date.')
        else:
            return None

    def csv_name(keyword, start_date=NOW.replace(months=-2), category=''):
        """ Converts keyword into filenames:
                'keyword_date_category_quarterly.csv'
        If --cik-file is specified, filename becomes: cik.csv
        """
        if isinstance(keyword, str):
            filename = keyword + " - "
            if args.category:
                filename += "[" + args.category + "] "
            if args.all_quarters:
                filename += args.all_quarters + " quarterly"
            elif args.all_years:
                filename += args.all_years + " yearly"
            elif args.ipo_quarters:
                filename += args.ipo_quarters
            else:
                filename += YYYY_MM(args.start_date).format("YYYY-MMM") \
                        + "~" + YYYY_MM(args.end_date).format("YYYY-MMM") + " full"
        elif isinstance(keyword, KeywordData):
            filename = keyword.cik
            if filename is None:
                filename = keyword.orig_keyword
        else:
            filename = keyword[0] # keyword: [cik, keyword, date]

        return filename.rstrip() + ".csv"

    def keyword_generator(keywords):
        "Shuffles keywords to avoid concurrent processes working on the same keyword."
        keywords = list(keywords)
        random.shuffle(keywords)
        for keyword in keywords:
            if os.path.exists(os.path.join(args.batch_output_path, csv_name(keyword))):
                continue
            yield keyword

    def output_results(IO_out, kw, quiet=None):
        writer = csv.writer(IO_out)
        if not quiet:
            if kw.desc=="Search term":
                writer.writerow(["Date", kw.keyword, kw.desc])
            else:
                writer.writerow(["Date", kw.keyword, kw.desc, kw.title])
        else:
            writer.writerow(["Date", kw.keyword])
        [writer.writerow([str(s) for s in interest]) for interest in kw.interest]



    args = parser.parse_args()
    if not missing_args(args):
        if args.keywords: # Single input
            keywords = {k.strip() for k in args.keywords.split(",")}

        elif args.batch_input_path:
            with open(args.batch_input_path) as source:
                keywords = [l.strip() for l in source.readlines() if l.strip() != ""]
                keywords = [s.replace(',','') for s in keywords]

        elif args.cik_file:
            with open(args.cik_file) as source:
                keywords = [f.strip().split('|') for f in source.readlines()]
                try:
                    assert all([len(k)==3 for k in keywords])
                except AssertionError:
                    print('--cik-file: Bad format, try using pipe delimited (|) data.')
                    sys.exit(1)

        if not py3:
            try:
                keywords = [k.decode('latin-1') for k in keywords]
            except AttributeError:
                pass

    start_date = YYYY_MM(args.start_date)
    end_date   = YYYY_MM(args.end_date)
    trend_generator = get_trends(keyword_generator(keywords),
                                trends_url=args.trends_url,
                                all_years=args.all_years,
                                all_quarters=args.all_quarters,
                                ipo_quarters=args.ipo_quarters,
                                start_date=start_date,
                                end_date=end_date,
                                username=args.username,
                                password=args.password,
                                throttle=args.throttle,
                                category=args.category)

    for keyword_data in trend_generator:
        if args.batch_output_path == "terminal":
            output_results(sys.stdout, keyword_data)
        else:
            if not os.path.exists(args.batch_output_path):
                os.makedirs(args.batch_output_path)

            output_filename = os.path.join(args.batch_output_path, \
                                csv_name(keyword_data))

            with open(output_filename, 'w+') as f:
                output_results(f, keyword_data, args.quiet_io)



def get_trends(keyword_gen, trends_url=DEFAULT_TRENDS_URL, login_url=DEFAULT_LOGIN_URL, auth_url=DEFAULT_AUTH_URL, username=None, password=None, ipo_quarters=None, all_quarters=None, all_years=None, start_date=arrow.utcnow().replace(months=-2), end_date=arrow.utcnow(), throttle=0, category=None):
    """ Gets a collection of trends. Requires --keywords, --username and --password flags.

        Arguments:
            --keywords: The sequence of keywords to query trends on
            --trends_url: The address at which we can obtain trends
            --username: Username to provide when authenticating with Google
            --password: Password to provide when authenticating with Google
            --throttle: Number of seconds to wait between requests
            --categories: A category specification such as 0-7-37 for banking
            --start_date: The earliest records to include in the query
            --end_date: The oldest records to include in the query
            --all_quarters: Starting date (YYYY-MM) for rolling quarterly queries.
            --all_years: Starting  date (YYYY-MM) for rolling yearly queries.

        Returns a generator of KeywordData
    """

    def throttle_rate(seconds):
        """Throttles query speed in seconds. Try --throttle "random" (1~4 seconds)"""
        if str(seconds).isdigit() and seconds > 0:
            sleep(float(seconds))
        elif seconds=="random":
            sleep(float(random.randint(1,3)))


    def query_parameters(start_date, end_date, keywords, category):
        "Formats query parameters into a dictionary and passes to session.get()"
        months = int(max((end_date - start_date).days, 30) / 30) # Number of months back
        params = {"export": 1, "content": 1}
        params["date"] = "{0} {1}m".format(start_date.strftime("%m/%Y"), months)
        # combine topics into a joint query -> q: query
        params["q"] = ", ".join([k.topic for k in keywords])
        if category:
            params["cat"] = category
        return params


    def get_response(url, params, cookies):
        "Calls GET and returns a list of the reponse data."
        response = sess.get(url, params=params, cookies=cookies, allow_redirects=True, stream=True)

        if response.headers["content-type"] == EXPECTED_CONTENT_TYPE:
            if sys.version_info.major==3:
                return [x.decode('utf-8') for x in response.iter_lines()]
            else:
                return list(response.iter_lines())
        elif response.headers["content-type"] == 'text/html; charset=UTF-8':
            if "quota" in response.text.strip().lower():
                raise QuotaException("\n\nThe request quota has been reached. " +
                        "This may be either the daily quota (~500 queries?) or the rate limiting quota. " +
                        "Try adding the --throttle argument to avoid rate limiting problems.")

            elif "currently unavailable" in response.text.strip().lower():
                print(response.text.strip().lower())
                print("\nNo interest for this category--'currently unavailable' " +
                    "\ncontent type: {}... returning 0\n\n".format(
                        response.headers["content-type"]))

                qdate = params["date"].split(' ')[0]
                qdate = arrow.get(qdate, 'MM/YYYY').strftime('%b %Y')
                topic = params["q"].split(',')[0]
                return [topic, "Worldwide; " + qdate, ""]

            else:
                print('\n', response.text.strip().lower(), '\n')
                raise FormatException(("\n\nUnexpected content type {0}. " +
                    "Maybe an invalid category or date was supplied".format(
                        response.headers["content-type"])))


    def process_response(response_data):
        "Filters raw response.get data for dates and interest over time counts."
        try:
            start_row = response_data.index(INTEREST_OVER_TIME_HEADER)
        except (AttributeError, ValueError) as e:
            return response_data # handle in check_no_data()

        formatted_data = []
        for line in response_data[start_row+1:]:
            if line.strip() == "":
                break # reached end of interest over time
            else:
                formatted_data.append(line.strip().split(','))
        return formatted_data


    def check_no_data(queried_data):
        "Check if query is empty. If so, format data accordingly."
        if 'Worldwide; ' in queried_data[1] and queried_data[2]=="":
            try:
                date = queried_data[1][-8:]
                date = arrow.get(date, 'MMM YYYY')
                no_data = [date, 0]
            except:
                date = queried_data[1][-4:]
                date = arrow.get(date, 'YYYY')
                no_data = [date, 0]
                pass
            print("Zero interest for '{0}'".format(keywords[0].title))
            return [no_data]
        else:
            return queried_data[1:]


    def rolling_query(begin_period, end_period, window={'months':0,'years':1}):
        "Iterates through queries by either quarterly or yearly moving windows"

        aw_range = arrow.Arrow.range
        current_period = arrow.utcnow()
        offset = 3 if window['months'] != 0 else 1
        win_type = 'month' if window['months'] != 0 else 'year'

        start_range = aw_range(win_type, YYYY_MM(begin_period),
                                         YYYY_MM(current_period))
        ended_range = aw_range(win_type, YYYY_MM(begin_period).replace(**window),
                                         YYYY_MM(current_period).replace(**window))
        # .replace(**window) increments/decrements months/years

        start_range = [r.datetime for r in start_range][::offset]
        ended_range = [r.datetime for r in ended_range][::offset]
        ended_range[-1] = YYYY_MM(arrow.utcnow()).datetime
        # Set last date to current month

        all_data = []
        for start, end in zip(start_range, ended_range):
            print("Querying period: {s} ~ {e}".format(s=start.date(),
                                                      e=end.date()))
            throttle_rate(throttle)
            params = query_parameters(start, end, keywords, category)
            query_data = get_response(trends_url.format(domain=domain), params, cookies)
            query_data = check_no_data(process_response(query_data))
            all_data.append(query_data)

        heading = ["Date", keywords[0].title]
        return [heading] + sum(all_data, [])


    def ipo_quarters_fn(filing_date):
        """Gets interest data (quarterly) for the 6 months before and 12 months after
        specified date, then gets interest data for the whole period and merges this data. Returns daily data over the period.
        """

        aw_range = arrow.Arrow.range
        begin_period = arrow.get(filing_date).replace(months=-6)
        ended_period = arrow.get(filing_date).replace(months=+15)

        start_range = aw_range('month', YYYY_MM(begin_period),
                                        YYYY_MM(ended_period))
        ended_range = aw_range('month', YYYY_MM(begin_period).replace(months=3),
                                        YYYY_MM(ended_period).replace(months=3))

        start_range = [r.datetime for r in start_range][::3]
        ended_range = [r.datetime for r in ended_range][::3]

        last_week = arrow.utcnow().replace(weeks=-1).datetime
        start_range = [d for d in start_range if d < last_week]
        ended_range = [d for d in ended_range if d < last_week]
        if len(ended_range) < len(start_range):
            ended_range += [last_week]

        all_data = []
        for start, end in zip(start_range, ended_range):
            if start > last_week:
                break

            print("Querying period: {s} ~ {e}".format(s=start.date(),
                                                      e=end.date()))
            throttle_rate(throttle)
            params = query_parameters(start, end, keywords, category)
            query_data = get_response(trends_url.format(domain=domain), params, cookies)
            query_data = check_no_data(process_response(query_data))
            if all([vals==0 for date,vals in query_data]):
                query_data = [[date, 0] for date in arrow.Arrow.range('month', start, end)]
            all_data.append(query_data)


        s = begin_period.replace(weeks=-2).datetime
        e1 = arrow.get(ended_range[-1]).replace(months=+1).datetime
        e2 = arrow.utcnow().replace(weeks=-1).datetime
        e = min(e1,e2)

        print("Merging with overall period: {s} ~ {e}".format(s=s.date(), e=e.date()))
        params = query_parameters(s, e, keywords, category)
        query_data = get_response(trends_url.format(domain=domain), params, cookies)
        query_data = check_no_data(process_response(query_data))

        if len(query_data) > 1:
            # compute changes in IoI (interest over time) per quarter
            # cannot mix quarters due to normalization within quarters
            # just index the first change in IoI to 1.
            all_ioi_delta = []
            qdat_interp = []
            for quarter_data in all_data:
                if quarter_data != []:
                    quarter_data = [x for x in quarter_data if x[1] != '']
                    all_ioi_delta += list(zip(*change_in_ioi(*zip(*quarter_data))))
                    qdat_interp += interpolate_ioi(*zip(*quarter_data))[1]

            qdate = [date for date, delta_ioi in all_ioi_delta]
            delta_ioi = [delta_ioi for date, delta_ioi in all_ioi_delta]
            ydate = [date[-10:] if len(date) > 10 else date for date,ioi in query_data]
            yIoI  = [float(ioi) for date,ioi in query_data]
            ydate, yIoI = interpolate_ioi(ydate, yIoI)

            # match quarterly and yearly dates and get correct delta IoI
            # common_date = [x for x in ydate+qdate if x in ydate and x in qdate]
            common_date = sorted(set(ydate) & set(qdate))

            delta_ioi = [delta_ioi for date,delta_ioi in zip(qdate, delta_ioi)
                        if date in common_date]
            y_ioi = [y for x,y in zip(ydate, yIoI) if x in common_date]

            # calculate daily %change in IoI and adjust weekly values
            adj_IoI = [ioi*mult for ioi,mult in zip(y_ioi, delta_ioi)]

            adj_all_data = [[str(date.date()), round(ioi, 2)]
                            for date,ioi in zip(common_date, adj_IoI)]
        else:
            adj_all_data = [[str(date.date()), int(zero)]
                for date, zero in zip(*interpolate_ioi(*zip(*sum(all_data,[]))))]

        # embed()
        # import pandas as pd
        # import matplotlib.pyplot as plt
        # from ggplot import ggplot, geom_line, ggtitle, ggsave, scale_colour_manual, ylab, xlab, aes

        # ydat = pd.DataFrame(list(zip(common_date, y_ioi)), columns=["Date", 'Weekly series'])
        # mdat = pd.DataFrame(list(zip(common_date, adj_IoI)), columns=['Date', 'Merged series'])
        # qdat = pd.DataFrame(list(zip(common_date, qdat_interp)), columns=['Date', 'Daily series'])
        # ddat = ydat.merge(mdat, on='Date').merge(qdat,on='Date')
        # ddat['Date'] = list(map(pd.to_datetime, ddat['Date']))

        # ydat['Date'] = list(map(pd.to_datetime, ydat['Date']))
        # mdat['Date'] = list(map(pd.to_datetime, mdat['Date']))
        # qdat['Date'] = list(map(pd.to_datetime, qdat['Date']))

        # newdat = pd.melt(ddat[['Date', 'Merged series', 'Daily series', 'Weekly series']], id_vars='Date')
        # newdat.sort('variable', inplace=True)


        # colors = [
        #     (0.467, 0.745, 0.88), # blue
        #     (0.706, 0.486, 0.78), # purple
        #     (0.839, 0.373, 0.373) # red
        # ]

        # show = ggplot(aes(x='Date', y='value', color='variable'), data=newdat) + \
        #     geom_line(aes(x='Date', y='Daily series'), data=qdat, alpha=0.5, color=colors[0]) + \
        #     geom_line(aes(x='Date', y='Merged series'), data=mdat, alpha=0.9, color=colors[1]) + \
        #     geom_line(aes(x='Date', y='Weekly series'), data=ydat, alpha=0.5, color=colors[2], size=1.5) + \
        #     geom_line(aes(x='Date', y='value', color='variable'), data=newdat, alpha=0.0) +  scale_colour_manual(values=colors) + \
        #     ggtitle("Interest over time for '{}'".format(keywords[0].keyword)) + \
        #     ylab("Interest Over Time") + xlab("Date")

        # # ggsave(filename='merged_{}'.format(keywords[0].keyword), width=15, height=4)


        heading = ["Date", keywords[0].title]
        return [heading] + adj_all_data




    sess, cookies, domain = authenticate_with_google(username, password,
                                                     login_url=login_url,
                                                     auth_url=auth_url)

    while True:
        try:         # try to get correct keywords
            keywords = disambiguate_keywords(keyword_gen, sess, cookies)
            # keywords -> KeywordData object(s).
            # Default: NUM_KEYWORDS_PER_REQUEST = 1
        except StopIteration:
            break

        for keyword in keywords:
            # Default: NUM_KEYWORDS_PER_REQUEST = 1
            try:
                print("="*60, "\n{k}: {c}".format(k=keyword.__unicode__(), c=category))
            except:
                pass
            if keyword.cik:
                print('cik:', keyword.cik, '\nfiling date: ', keyword.filing_date)

        if all_quarters:
            # Rolling quarterly period queries
            all_data = rolling_query(all_quarters, window={'months':3,'years':0})
        elif all_years:
            # Rolling yearly period queries
            all_data = rolling_query(all_years, window={'months':0,'years':1})
        elif ipo_quarters:
            # Rolling quarterly period queries within start and end dates
            filing_date = ipo_quarters[:7]
            all_data = ipo_quarters_fn(filing_date)
        elif keywords[0].cik:
            # dates obtained from --cik-filing
            filing_date = keywords[0].filing_date
            all_data = ipo_quarters_fn(filing_date)
        else:
            # Single period queries
            throttle_rate(throttle)
            params = query_parameters(start_date, end_date, keywords, category)
            try:
                all_data = get_response(trends_url.format(domain=domain), params, cookies)
                all_data = check_no_data(process_response(all_data))
            except (FormatException, AttributeError, ValueError):
                all_data = [[arrow.get(str(x), 'YYYY'), 0] for x in range(2004,2015)]

            heading  = ["Date", keywords[0].title]
            all_data = [heading] + all_data

        # assign (date, counts) to each KeywordData object
        for row in all_data[1:]:
            if row[1] == "":
                break
            date, counts = parse_row(row)
            for i in range(len(counts)):
                try:
                    keywords[i].add_interest_data(date, counts[i])
                except:
                    print("No data for keywords: {1}".format(keywords))
                    raise

        # yield KeywordData objects
        for kw in keywords:
            yield kw



def parse_row(raw_row):
    """ Parses a raw row of data into a more meaningful representation
        Arguments: raw_row -- A list of strings

        Returns a 2-tuple (date, [count1, count2, ..., countn])
        representing a date and associated counts for that date"""
    # if py3:
    #     raw_date, *counts = [x for x in raw_row] # python 3.3 feature only.

    raw_date = raw_row[0]
    if type(raw_date) == str:
        try:
            if len(raw_date) > 10: # indicates date range rather than date, grab first
                raw_date = raw_date[:10]
        except Exception:
            raise FormatException("Unable to parse data from row {0}.".format(raw_row))
    date_obj = arrow.get(raw_date).date()
    counts = [int(x) for x in raw_row[1:]]

    return (date_obj, counts)


def YYYY_MM(date_obj):
    """Removes day. Formats dates from YYYY-MM-DD to YYYY-MM. Also turns date objects into Arrow objects."""
    date_obj = arrow.get(date_obj)
    return arrow.get(date_obj.format("YYYY-MM"))








if __name__ == "__main__":
    main()
    print("="*60)
    print("OK. Done.")

