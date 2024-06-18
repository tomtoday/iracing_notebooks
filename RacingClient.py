import base64
import hashlib
import os
from http.cookiejar import LWPCookieJar
from pathlib import Path
import datetime
import requests
import json


class RacingClient:
    """
    RacingClient is an interfacing class for the iRacing Data API which is discussed on the forum
    at https://forums.iRacing.com/discussion/15068/general-availability-of-data-api/p1 with the
    JSON documentation available at https://members-ng.iracing.com/data/doc.  Both require authentication.

    Copyright (c) Dec 2022 Chris Davies <chris@byteinsight.co.uk>

    I must give full credit to Jason Dilworth for https://github.com/jasondilworth56/iRacingdataapi which
    was my starting point. Hopefully I have highlighted all of Jason's functions where I have used them without change.

    In this version I have:
    - documented each of the end point calls.
    - added try/except statements for greater robustness.
    - added an export feature so the results of each endpoint call can easily be saved to file.

    The file is divided into 3 sections as ordered:
    - PRIVATE ADMIN FUNCTIONS: These are mostly Jason's methods and except for the addition of try/except.
        They provide the 'coms' layer between RacingClient and the iRacing API
    - BUILDER FUNCTIONS: These methods are used by the API End Points when preparing the call and processing the returns.
    - API ENDPOINTS:  These are the end points provided by iRacing. They should be in order as per the documentation.

    At the bottom of the file I have set up an example on how to call RacingClient with multiple endpoint calls.
    This is also my testing record!

    @todo check that any required variables are indicated and remove keyword arguments in those instances.
    @todo complete testing - some of the endpoints were not returning data with the args provided in week 1.
    @todo process some of the data returned where it is returned as chunks or data_urls

    """

    debug = False
    global_cust_id = None

    def __init__(self, _username, _password, _cust_id, _files_root=None, _json_folder=None):
        """

        When we create an instance of the RacingClient we need to provide username & password for authentication
        on the iRacing Service, Cust_ID is used where data returns are limited to the authenticated user or as a
        fallback when an alternative is not provided.   Files Root and JSON folder are the system path and folder
        where any exports should be saved.

        :param _username: The username that can be authenticated on the iRacing Service
        :param _password: Password matching username above.
        :param _cust_id: The cust-id for the user above.
        :param _files_root: The system folder where exports are to be saved.
        :param _json_folder: The folder within the system folder to save JSON exports.
        :return: None
        """
        self.authenticated = False
        self.session = requests.Session()
        self.base_url = "https://members-ng.iRacing.com"

        self.username = _username
        self.encoded_password = self._encode_password(_username, _password)
        self.global_cust_id = _cust_id

        self.files_root = _files_root
        self.json_folder = _json_folder

    ##### PRIVATE ADMIN FUNCTIONS #####
    @staticmethod
    def _encode_password(username, password):
        """
        Taken From Dilworth's iRacing client api

        :param username:
        :param password:
        :return:
        """
        initial_hash = hashlib.sha256((password + username.lower()).encode('utf-8')).digest()
        return base64.b64encode(initial_hash).decode('utf-8')

    def _login(self, cookie_file=None):
        """
        From Dilworth's iRacing client api

        :param cookie_file:
        :return:
        """
        self.print_data("Authenticating with iRacing", None)
        if cookie_file:
            self.session.cookies = LWPCookieJar(cookie_file)
            if not os.path.exists(cookie_file):
                self.session.cookies.save()
            else:
                self.session.cookies.load(ignore_discard=True)
        headers = {'Content-Type': 'application/json'}
        data = {"email": self.username, "password": self.encoded_password}

        try:
            r = self.session.post('https://members-ng.iracing.com/auth', headers=headers, json=data, timeout=5.0)
        except requests.Timeout:
            raise RuntimeError("Login timed out")
        except requests.ConnectionError:
            raise RuntimeError("Connection error")
        else:
            response_data = r.json()
            if r.status_code == 200 and response_data['authcode']:
                if cookie_file:
                    self.session.cookies.save(ignore_discard=True)
                self.authenticated = True
                return "Logged in"
            else:
                raise RuntimeError("Error from iRacing: ", response_data)

    def _build_url(self, endpoint):
        """
        From Dilworth's iRacing client api
        :param endpoint:
        :return:
        """
        return self.base_url + endpoint

    def _get_resource_or_link(self, url, payload=None):
        """
        From Dilworth's iRacing client api

        :param url:
        :param payload:
        :return:
        """
        if not self.authenticated:
            self._login()
            return self._get_resource_or_link(url, payload=payload)

        r = self.session.get(url, params=payload)

        if r.status_code == 401:
            # unauthorised, likely due to a timeout, retry after a login
            self.authenticated = False

        if r.status_code != 200:
            raise RuntimeError(r.json())
        data = r.json()
        if not isinstance(data, list) and "link" in data.keys():
            return [data["link"], True]
        else:
            return [data, False]

    def _get_resource(self, endpoint, payload=None):
        """
        From Dilworth's iRacing client api
        :param endpoint:
        :param payload:
        :return:
        """
        request_url = self._build_url(endpoint)
        try:
            resource_obj, is_link = self._get_resource_or_link(request_url, payload=payload)
            if not is_link:
                return resource_obj
            r = self.session.get(resource_obj)
            if r.status_code != 200:
                raise RuntimeError(r.json())
            return r.json()
        except ConnectionError as error:
            print(error)
            return None

    def _get_chunks(self, chunks):
        """
        From Dilworth's iRacing client api
        :param chunks:
        :return:
        """
        base_url = chunks["base_download_url"]
        urls = [base_url + x for x in chunks["chunk_file_names"]]
        list_of_chunks = [self.session.get(url).json() for url in urls]
        output = [item for sublist in list_of_chunks for item in sublist]

        return output

    ##### BUILDER FUNCTIONS #####

    def get_cust_id(self, cust_id):
        """
        Tries to get a cust_id and falls back on self.cust_id.
        Raises Runtime if none exist.
        :param cust_id:
        :return:
        """
        if not cust_id:
            if self.global_cust_id:
                return self.global_cust_id
            else:
                raise RuntimeError("Please supply a cust_id")
        return cust_id

    def print_data(self, title, data, force=False):
        """
        Print Data function for debugging.
        :param title:
        :param data:
        :param force:
        :return:
        """
        try:
            if self.debug or force:
                if data is not None:
                    print(title)
                    print(str(data).encode('cp1252', errors='replace').decode('cp1252'))
                else:
                    print(title, "No Data Provided")
        except UnicodeEncodeError as uee:
            print("print_data", uee)

    def raw_to_json(self, file_name, raw_data):
        """
        Exports the raw data into a JSON file for saving.
        :param file_name:
        :param raw_data:
        :return:
        """
        export_path = os.path.join(self.files_root, self.json_folder)
        Path(export_path).mkdir(parents=True, exist_ok=True)
        full_path = None
        try:
            full_path = os.path.join(self.files_root, self.json_folder, file_name)
            with open(full_path, 'w', encoding='utf-8') as f:
                json.dump(raw_data, f, ensure_ascii=False, indent=4)
        except UnicodeEncodeError as uee:
            print("raw_to_json - UnicodeEncodeError", uee)
            print(full_path)
        except PermissionError as pe:
            print("raw_to_json - PermissionError", pe)
            print(full_path)

    @staticmethod
    def print_error(function_name, error_type, error):
        """ Class wide print function for exception errors. At some point I'd make this a logging function.
        :param function_name: name of the calling function.
        :param error_type: the catch exception.
        :param error: the error reported
        """
        print(f"{function_name}: {error_type} = {error}")

    ##### API ENDPOINTS #####

    ##### CARS #####
    def get_car_assets(self, export=False):
        """

        Gets the extended copy and image links etc. associated with the cars.
        Image paths are relative to https://images-static.iRacing.com/

        link: https://members-ng.iRacing.com/data/car/assets
        expirationSeconds: 900

        :param export: (boolean) should the file be exported to JSON
        :return: dict All data retrieved is returned.
        """
        try:
            raw_data = self._get_resource("/data/car/assets")

        except RuntimeError as error:
            self.print_error("get_car_assets", "RuntimeError", str(error))
            return None

        if export:
            self.raw_to_json('cars_assets.json', raw_data)
        return raw_data

    def get_car(self, export=False):
        """
        Gets a list of all the cars

        link: https://members-ng.iRacing.com/data/car/get
        expirationSeconds: 900

        :param export: (boolean) should the file be exported to JSON
        :return: dict All data retrieved is returned.
        """
        try:
            raw_data = self._get_resource("/data/car/get")

        except RuntimeError as error:
            self.print_error("get_car", "RuntimeError", str(error))
            return None

        if export:
            self.raw_to_json('cars.json', raw_data)
        return raw_data

    ##### CAR CLASS #####
    def get_carclass(self, export=False):
        """
        Returns cars grouped by their class.

         link: https://members-ng.iRacing.com/data/carclass/get
         expirationSeconds: 900

         :param export: (boolean) should the file be exported to JSON
         :return: dict All data retrieved is returned.
         """
        try:
            raw_data = self._get_resource("/data/carclass/get")

        except RuntimeError as error:
            self.print_error("get_carclass", "RuntimeError", str(error))
            return None

        if export:
            self.raw_to_json('car_class.json', raw_data)
        return raw_data

    ##### CONSTANTS #####
    def get_categories(self, export=False):
        """

        Returns the categories (license classes)
        Constant; returned directly as an array of objects

         link: https://members-ng.iRacing.com/data/constants/categories
         expirationSeconds: 900

         :param export: (boolean) should the file be exported to JSON
         :return: dict All data retrieved is returned.
         """
        try:
            raw_data = self._get_resource("/data/constants/categories")

        except RuntimeError as error:
            self.print_error("get_categories", "RuntimeError", str(error))
            return None

        if export:
            self.raw_to_json('categories.json', raw_data)
        return raw_data

    def get_divisions(self, export=False):
        """
         Returns the 12 divisions (1-10, -1(all) and Rookie)
         Constant; returned directly as an array of objects

         link: https://members-ng.iRacing.com/data/constants/divisions
         expirationSeconds: 900

         :param export: (boolean) should the file be exported to JSON
         :return: dict All data retrieved is returned.
         """
        try:
            raw_data = self._get_resource("/data/constants/divisions")

        except RuntimeError as error:
            self.print_error("get_divisions", "RuntimeError", str(error))
            return None

        if export:
            self.raw_to_json('divisions.json', raw_data)
        return raw_data

    def get_event_types(self, export=False):
        """
         Returns the 4 event types: 2: Practice, 3: Quali, 4: TT & 5: Race
         Constant; returned directly as an array of objects

         link: https://members-ng.iRacing.com/data/constants/event_types
         expirationSeconds: 900

         :param export: (boolean) should the file be exported to JSON
         :return: dict All data retrieved is returned.
         """
        try:
            raw_data = self._get_resource("/data/constants/event_types")

        except RuntimeError as error:
            self.print_error("get_event_types", "RuntimeError", str(error))
            return None

        if export:
            self.raw_to_json('event_types.json', raw_data)
        return raw_data

    ##### DRIVER STATS BY CATEGORY - need to revisit this #####
    def driver_stats_by_category(self, label="oval", export=True):
        """

        link: https://members-ng.iRacing.com/data/driver_stats_by_category/...
        expirationSeconds: 900

        :param label:
        :param export: (boolean) should the file be exported to JSON
        :return: dict All data retrieved is returned.
        """

        category_urls = {
            'oval': "/data/driver_stats_by_category/oval",
            'sports_car': "/data/driver_stats_by_category/sports_car",
            'formula_car': "/data/driver_stats_by_category/formula_car",
            'road': "/data/driver_stats_by_category/road",
            'dirt_oval': "/data/driver_stats_by_category/dirt_oval",
            'dirt_road': "/data/driver_stats_by_category/dirt_road",
        }

        try:
            label_url = category_urls.get(label, None)
            print(label_url)
        except ValueError as error:
            self.print_error("driver_stats_by_category", "ValueError", str(error))
            return None

        try:
            raw_data = self._get_resource(label_url)
            print(raw_data)
        except RuntimeError as error:
            self.print_error("driver_stats_by_category", "RuntimeError", str(error))
            return None

        if export:
            self.raw_to_json(f'driver_stats_by_category_{label}.json', raw_data)
        return raw_data

    ##### HOSTED #####
    def hosted_combined_sessions(self, package_id=None, export=False):
        """
        Sessions that can be joined as a driver or spectator, and also includes non-league pending sessions for the user.

        link: https://members-ng.iRacing.com/data/hosted/combined_sessions
        expirationSeconds: 60

        :param package_id: (number) If set, return only sessions using this car or track package ID.
        :param export: (boolean) should the file be exported to JSON
        :return: dict All data retrieved is returned.
        """
        try:
            payload = {}
            if package_id:
                payload["package_id"] = package_id
            raw_data = self._get_resource("/data/hosted/combined_sessions", payload=payload)

        except RuntimeError as error:
            self.print_error("hosted_combined_sessions", "RuntimeError", str(error))
            return None

        if export:
            self.raw_to_json(f"hosted_combined_sessions_{package_id}.json", raw_data)
        return raw_data

    def hosted_sessions(self, export=False):
        """
        Sessions that can be joined as a driver. Without spectator and non-league pending sessions for the user.

        link: https://members-ng.iRacing.com/data/hosted/sessions
        expirationSeconds: 60

        :param export: (boolean) should the file be exported to JSON
        :return: dict All data retrieved is returned.
        """
        try:
            payload = {}
            raw_data = self._get_resource("/data/hosted/sessions", payload=payload)
        except RuntimeError as error:
            self.print_error("hosted_sessions", "RuntimeError", str(error))
            return None

        if export:
            self.raw_to_json("hosted_sessions.json", raw_data)
        return raw_data

    ##### LEAGUE #####
    def league_cust_league_sessions(self, mine=False, package_id=None, export=False):
        """

        link: https://members-ng.iRacing.com/data/league/cust_league_sessions
        expirationSeconds: 900

        :param mine: (boolean) If true, return only sessions created by this user.
        :param package_id: (number) If set, return only sessions using this car or track package ID.
        :param export: (boolean) should the file be exported to JSON
        :return: dict All data retrieved is returned.
        """
        try:
            payload = {"mine": mine}
            if package_id:
                payload["package_id"] = package_id
            raw_data = self._get_resource("/data/league/cust_league_sessions", payload=payload)

        except RuntimeError as error:
            self.print_error("league_cust_league_sessions", "RuntimeError", str(error))
            return None

        if export:
            self.raw_to_json("league_cust_league_sessions.json", raw_data)
        return raw_data

    def get_league_directory(self, search="", tag="", restrict_to_member=False, restrict_to_recruiting=False,
                             restrict_to_friends=False, restrict_to_watched=False, minimum_roster_count=0,
                             maximum_roster_count=999, lower_bound=1, upperbound=None, sort=None, order="asc", export=False):
        """
        Returns list of leagues that match the search criteria.

        link: https://members-ng.iRacing.com/data/league/directory
        expirationSeconds: 900

        :param search: (string) Will search against league name, description, owner, and league ID.
        :param tag: (string) One or more tags, comma-separated.
        :param restrict_to_member: (boolean) If true include only leagues for which customer is a member.
        :param restrict_to_recruiting:(boolean) If true include only leagues which are recruiting.
        :param restrict_to_friends: (boolean) If true include only leagues owned by a friend.
        :param restrict_to_watched: (boolean) If true include only leagues owned by a watched member.
        :param minimum_roster_count:(number) If set include leagues with at least this number of members.
        :param maximum_roster_count: (number) If set include leagues with no more than this number of members.
        :param lower_bound: (number) First row of results to return. Defaults to 1.
        :param upperbound:(number) Last row of results to return. Defaults to lower_bound + 39.
        :param sort: (string) One of relevance, league_name, display_name, roster_count. display_name is owners' name. Defaults to relevance.
        :param order: (string) One of asc or desc. Defaults to asc.
        :param export: (boolean) should the file be exported to JSON
        :return: dict All data retrieved is returned.
        """
        try:
            params = locals()
            payload = {}
            for x in params.keys():
                if x != "self":
                    payload[x] = params[x]
            raw_data = self._get_resource("/data/league/directory", payload=payload)

        except RuntimeError as error:
            self.print_error("get_league_directory", "RuntimeError", str(error))
            return None

        if export:
            self.raw_to_json('league_directory.json', raw_data)
        return raw_data

    def league_get(self, league_id=None, include_licenses=False, export=False):
        """

        link: https://members-ng.iRacing.com/data/league/get
        expirationSeconds: 900

        :param league_id: (number) Required
        :param include_licenses: (boolean) For faster responses, only request when necessary.
        :param export: (boolean) should the file be exported to JSON
        :return: dict All data retrieved is returned.
        """
        try:
            if not league_id:
                raise RuntimeError("Please supply a league_id")

            payload = {"league_id": league_id, "include_licenses": include_licenses}
            raw_data = self._get_resource("/data/league/get", payload=payload)

        except RuntimeError as error:
            self.print_error("league_get", "RuntimeError", str(error))
            return None

        if export:
            self.raw_to_json(f"league_{league_id}.json", raw_data)
        return raw_data

    def league_get_points_systems(self, league_id, season_id=None, export=False):
        """
        Returns all the point systems available for the league provided.

        link: https://members-ng.iRacing.com/data/league/get_points_systems
        expirationSeconds: 900

        :param league_id: (number) Required
        :param season_id: (number) If included and the season is using custom points (points_system_id:2)
        then the custom points option is included in the returned list.
        Otherwise, the custom points option is not returned.
        :param export: (boolean) should the file be exported to JSON
        :return: dict All data retrieved is returned.
        """
        try:
            if not league_id:
                raise RuntimeError("Please supply a league_id")

            payload = {"league_id": league_id, 'season_id': season_id}
            raw_data = self._get_resource("/data/league/get_points_systems", payload=payload)

        except RuntimeError as error:
            self.print_error("league_get_points_systems", "RuntimeError", str(error))
            return None

        if export:
            self.raw_to_json(f"league_points_systems_{league_id}.json", raw_data)
        return raw_data

    # league_membership - need to revisit this.
    def league_membership(self, cust_id, include_league=False, export=False):
        """

        link: https://members-ng.iRacing.com/data/league/membership
        expirationSeconds: 900

        :param cust_id: (number) If different from the authenticated member, the following restrictions apply:
        - Caller cannot be on requested customer's block list or an empty list will result;
        - Requested customer cannot have their online activity preference set to hidden or an empty list will result;
        - Only leagues for which the requested customer is an admin and the league roster is not private are returned.
        :param include_league: (boolean)
        :param export: (boolean) should the file be exported to JSON
        :return: dict All data retrieved is returned.
        @todo Revisit this and work out who it can actually return.
        """
        try:
            payload = {"cust_id": cust_id}
            if include_league:
                payload["include_league"] = include_league
            raw_data = self._get_resource("/data/league/membership", payload=payload)

        except RuntimeError as error:
            self.print_error("league_membership", "RuntimeError", str(error))
            return None

        if export:
            filename = "membership.json"
            self.raw_to_json(filename, raw_data)

    def league_roster(self, league_id, include_licenses=False, export=False):
        """
        Returns a summary for the roster including count and a data_url to the roster information.

        link: https://members-ng.iRacing.com/data/league/get_points_systems
        expirationSeconds: 900

        :param league_id: (number) Required
        :param include_licenses: For faster responses, only request when necessary.
        :param export: (boolean) should the file be exported to JSON
        :return: dict All data retrieved is returned.
        """
        try:
            if not league_id:
                raise RuntimeError("Please supply a league_id")

            payload = {"league_id": league_id, 'include_licenses': include_licenses}
            raw_data = self._get_resource("/data/league/roster", payload=payload)

        except RuntimeError as error:
            self.print_error("league_roster", "RuntimeError", str(error))
            return None

        if export:
            self.raw_to_json(f"league_roster_{league_id}.json", raw_data)
        return raw_data

    def league_seasons(self, league_id, retired=False, export=False):
        """

        link: https://members-ng.iRacing.com/data/league/seasons
        expirationSeconds: 900

        :param league_id: (number) Required
        :param retired: If true include seasons which are no longer active
        :param export: (boolean) should the file be exported to JSON
        :return: dict All data retrieved is returned.
        """
        try:

            if not league_id:
                raise RuntimeError("Please supply a league_id")

            payload = {"league_id": league_id, "retired": retired}
            raw_data = self._get_resource("/data/league/seasons", payload=payload)

        except RuntimeError as error:
            self.print_error("league_seasons", "RuntimeError", str(error))
            return None

        if export:
            self.raw_to_json(f"league_seasons_{league_id}.json", raw_data)
        return raw_data

    def league_season_standings(self, league_id, season_id, car_class_id=None, car_id=None, export=False):
        """

        If car_class_id is included then the standings are for the car in that car class,
        otherwise they are for the car across car classes.

        link: https://members-ng.iRacing.com/data/league/season_standings
        expirationSeconds: 900

        :param league_id: (number) Required
        :param season_id: (number) Required
        :param car_class_id: (number)
        :param car_id: (number)
        :param export: (boolean) should the file be exported to JSON
        :return: dict All data retrieved is returned.
        """
        try:

            if not league_id or not season_id:
                raise RuntimeError("Please ensure you are supplying a league_id and season_id")
            payload = {"league_id": league_id, "season_id": season_id, "car_class_id": car_class_id, "car_id": car_id}

            raw_data = self._get_resource("/data/league/season_standings", payload=payload)

        except RuntimeError as error:
            self.print_error("league_season_standings", "RuntimeError", str(error))
            return None

        if export:
            self.raw_to_json(f"league_season_standings_{league_id}_{season_id}.json", raw_data)

        return raw_data

    def league_season_sessions(self, league_id, season_id, results_only=True, export=False):
        """

        link: https://members-ng.iRacing.com/data/league/season_sessions
        expirationSeconds: 900

        :param league_id: (number) Required
        :param season_id: (number) Required
        :param results_only: (boolean)
        :param export: (boolean) should the file be exported to JSON
        :return: dict All data retrieved is returned.
        """
        try:
            if not league_id or not season_id:
                raise RuntimeError("Please ensure you are supplying a league_id and season_id")

            payload = {"league_id": league_id, "season_id": season_id, "results_only": results_only}
            raw_data = self._get_resource("/data/league/season_sessions", payload=payload)

        except RuntimeError as error:
            self.print_error("league_season_sessions", "RuntimeError", str(error))
            return None

        if export:
            self.raw_to_json(f"league_season_sessions_{league_id}_{season_id}.json", raw_data)
        return raw_data

    ##### LOOKUP #####
    def lookup_club_history(self, season_year, season_quarter, export=False):
        """
        Seems to just return a list of clubs.
        Returns an earlier history if requested quarter does not have a club history.

        link: https://members-ng.iracing.com/data/lookup/club_history
        expirationSeconds: 900

        :param season_year: (number) Required
        :param season_quarter: (number) Required
        :param export: (boolean) should the file be exported to JSON
        :return: dict All data retrieved is returned.
        """
        try:
            if not season_year or not season_quarter:
                raise RuntimeError("Please ensure you are supplying a season_year and season_quarter")

            payload = {"season_year": season_year, "season_quarter": season_quarter}
            raw_data = self._get_resource("/data/lookup/club_history", payload=payload)

        except RuntimeError as error:
            self.print_error("lookup_club_history", "RuntimeError", str(error))
            return None

        if export:
            self.raw_to_json(f"club_history_{season_year}_{season_quarter}.json", raw_data)
        return raw_data

    def lookup_countries(self, export=False):
        """

        Returns a list of countries with their country codes.

         link: https://members-ng.iRacing.com/data/lookup/countries
         expirationSeconds: 900

         :param export: (boolean) should the file be exported to JSON
         :return: dict All data retrieved is returned.
         """
        try:
            raw_data = self._get_resource("/data/lookup/countries")

        except RuntimeError as error:
            self.print_error("lookup_countries", "RuntimeError", str(error))
            return None

        if export:
            self.raw_to_json('countries.json', raw_data)
        return raw_data

    def lookup_drivers(self, search_term=None, league_id=None, export=False):
        """

         Driver search function

         link: https://members-ng.iracing.com/data/lookup/drivers
         expirationSeconds: 900

         :param search_term: (string) Required: A cust_id or partial name for which to search
         :param league_id: (number) Narrow the search to the roster of the given league.

         :param export: (boolean) should the file be exported to JSON
         :return: dict All data retrieved is returned.
         """
        try:

            if not search_term:
                raise RuntimeError("Please supply a search_term")
            payload = {"search_term": search_term, "league_id": league_id}
            raw_data = self._get_resource("/data/lookup/drivers", payload=payload)

        except RuntimeError as error:
            self.print_error("lookup_drivers", "RuntimeError", str(error))
            return None

        if export:
            self.raw_to_json('drivers.json', raw_data)
        return raw_data

    # lookup_get - need to revisit this.
    def lookup_get(self, export=False):
        """

        @todo Figure out how this works.  Seems to be a generic get?

        ?weather=weather_wind_speed_units&weather=weather_wind_speed_max
        &weather=weather_wind_speed_min&licenselevels=licenselevels

        link: https://members-ng.iracing.com/data/lookup/get
        expiration: 900 Seconds

        :param export:
        :return:
        """

    def lookup_licenses(self, export=False):
        """

        Returns a list of licenses and the sublicenses.

         link: https://members-ng.iracing.com/data/lookup/licenses
         expirationSeconds: 900

         :param export: (boolean) should the file be exported to JSON
         :return: dict All data retrieved is returned.
         """
        try:
            raw_data = self._get_resource("/data/lookup/licenses")

        except RuntimeError as error:
            self.print_error("lookup_licenses", "RuntimeError", str(error))
            return None

        if export:
            self.raw_to_json('licenses.json', raw_data)
        return raw_data

    ##### MEMBER - Tested 10/06/2024 #####
    def member_awards(self, cust_id=None, export=False):
        """
        Defaults to the authenticated member.
        Returns a small 'data' dictionary including success; cust_id; and award_count.
        and a 'dataurl' to a JSON file which can be used to retrieve the individual awards.

        link: https://members-ng.iRacing.com/data/member/awards
        expiration: 900 Seconds

        :param cust_id: (number) defaults to the authenticated member.
        :param export: (boolean) should the file be exported to JSON
        :return: see above.
        """
        if cust_id is None:
            cust_id = self.get_cust_id(cust_id)
        try:
            payload = {"cust_id": cust_id}
            raw_data = self._get_resource("/data/member/awards", payload=payload)

        except RuntimeError as error:
            self.print_error("member_awards", "RuntimeError", str(error))
            return None

        if export:
            filename = f"member_awards_{cust_id}.json"
            self.raw_to_json(filename, raw_data)
        return raw_data

    def member_chart_data(self, cust_id=None, category_id=1, chart_type=1, export=False):
        """
        Member Chart Data returns a two point dictionary that can be used to plot data.

        link: https://members-ng.iraci…m/data/member/chart_data
        expiration: 900 Seconds

        :param cust_id: Defaults to the authenticated member
        :param category_id: 1 - Oval; 2 - Road; 3 - Dirt oval; 4 - Dirt road.
        :param chart_type: 1 - iRating; 2 - TT Rating; 3 - License/SR
        :param export: export a json file with the name member_chart_data_category_chart.json
        :return dictionary
        """
        cust_id = self.get_cust_id(cust_id)

        try:

            payload = {"category_id": category_id, "chart_type": chart_type}
            if cust_id:
                payload["cust_id"] = cust_id

            raw_data = self._get_resource("/data/member/chart_data", payload=payload)

        except RuntimeError as error:
            self.print_error("member_chart_data", "RuntimeError", str(error))
            return None

        if export:
            filename = f"member_chart_data_{cust_id}_cat{category_id}_chart{chart_type}.json"
            self.raw_to_json(filename, raw_data['data'])
        return raw_data

    def member_get(self, cust_id=None, include_licenses=False, export=False):
        """
        Retrieves basic membership data (not really useful).
        Can give a comma separated list of cust_ids e.g. ?cust_ids=2,3,4

        link: - https://members-ng.iRacing.com/data/member/get
        expiration: 900 Seconds

        :param cust_id: (number) Required.
        :param include_licenses: (boolean)
        :param export: (boolean) should the file be exported to JSON
        :return:
        """

        cust_id = self.get_cust_id(cust_id)

        try:
            payload = {"cust_ids": cust_id, "include_licenses": include_licenses}
            raw_data = self._get_resource("/data/member/get", payload=payload)

        except RuntimeError as error:
            self.print_error("member_get", "RuntimeError", str(error))
            return None

        if export:
            filename = f"member_{cust_id}.json"
            self.raw_to_json(filename, raw_data)
        return raw_data

    def member_info(self, export=False):
        """
        Always retrieves information on the authenticated member.

        link: https://members-ng.iRacing.com/data/member/info
        expiration: 900 Seconds

        :param export: (boolean) should the file be exported to JSON
        :return: dict All data retrieved is returned.
        """

        try:
            payload = {}
            raw_data = self._get_resource("/data/member/info", payload=payload)

        except RuntimeError as error:
            self.print_error("member_info", "RuntimeError", str(error))
            return None

        if export:
            filename = "member_info.json"
            self.raw_to_json(filename, raw_data)
        return raw_data

    def member_participation_credits(self, export=False):
        """
        Always returns the participation for the authenticated member in the form of a series list where participation has been earned.

        link:	https://members-ng.iRacing.com/data/member/participation_credits
        expiration: 900 Seconds

        :param export: (boolean) should the file be exported to JSON
        :return: dict All data retrieved is returned.
        """

        try:
            payload = {}
            raw_data = self._get_resource("/data/member/participation_credits", payload=payload)

        except RuntimeError as error:
            self.print_error("member_participation_credits", "RuntimeError", str(error))
            return None

        if export:
            filename = "member_participation_credits.json"
            self.raw_to_json(filename, raw_data)
        return raw_data

    def member_profile(self, cust_id=None, export=False):
        """
        Probably the most useful call for an individual user.  Returns information on:
        recent_awards, activity, image_url, profile, member_info, field_defs, license_history & recent_events
        plus a few other individual values.

        link:	https://members-ng.iRacing.com/data/member/profile
        expirationSeconds:	900

        :param cust_id: (number) Defaults to the authenticated member.
        :param export: (boolean) should the file be exported to JSON
        :return: dict All data retrieved is returned.
        """

        cust_id = self.get_cust_id(cust_id)
        try:
            payload = {"cust_id": cust_id}
            raw_data = self._get_resource("/data/member/profile", payload=payload)

        except RuntimeError as error:
            self.print_error("member_profile", "RuntimeError", str(error))
            return None

        if export:
            self.raw_to_json(f"member_profile_{cust_id}.json", raw_data)
        return raw_data

    ##### RESULTS #####

    def results_get(self, subsession_id=None, include_licenses=False, export=False):
        """
        Get the results of a subsession, if authorized to view them. series_logo image paths
        are relative to https://images-static.iRacing.com/img/logos/series/.

        link: https://members-ng.iRacing.com/data/results/get
        expirationSeconds:	900

        :param subsession_id: (number) Required
        :param include_licenses: (boolean)
        :param export: (boolean) should the file be exported to JSON
        :return: dict All data retrieved is returned.
        """

        if not subsession_id:
            raise RuntimeError("Please supply a subsession_id")

        try:
            payload = {
                "subsession_id": subsession_id,
                "include_licenses": include_licenses}

            raw_data = self._get_resource("/data/results/get", payload=payload)
            self.print_data("Result", raw_data)

        except RuntimeError as error:
            self.print_error("results_get", "RuntimeError", str(error))
            return None

        if export:
            filename = f"result_{subsession_id}.json"
            self.raw_to_json(filename, raw_data)

        return raw_data

        # dictionary of the lap data for the given sub session id.

    def result_event_log(self, subsession_id=None, simsession_number=0, export=False):
        """
        Returns a dictionary of the events e.g. lead changes and penalities for the given sub session id
        link: https://members-ng.iRacing.com/data/results/event_log
        expirationSeconds:	900

        :param subsession_id: (number) Required
        :param simsession_number: (number) The main event is 0; the preceding event is -1, and so on.
        :param export: (boolean) should the file be exported to JSON
        :return: dict All data retrieved is returned.
        """

        if not subsession_id:
            raise RuntimeError("Please supply a subsession_id")

        try:
            payload = {
                "subsession_id": subsession_id,
                "simsession_number": simsession_number,
            }

            raw_data = self._get_resource("/data/results/event_log", payload=payload)

        except RuntimeError as error:
            self.print_error("result_event_log", "RuntimeError", str(error))
            return None

        chunks = self._get_chunks(raw_data["chunk_info"])

        if export:
            filename = f"result_event_log_{subsession_id}_simsession_{simsession_number}.json"
            self.raw_to_json(filename, chunks)

        return chunks

    def result_lap_chart_data(self, subsession_id=None, simsession_number=0, export=False):
        """
        Returns a dictionary of the lap data for the given sub session id.

        link: https://members-ng.iRacing.com/data/results/lap_chart_data
        expirationSeconds:	900

        :param subsession_id: (number) Required
        :param simsession_number: (number) The main event is 0; the preceding event is -1, and so on.
        :param export: (boolean) should the file be exported to JSON
        :return: dict All data retrieved is returned.
        """

        if not subsession_id:
            raise RuntimeError("Please supply a subsession_id")

        try:
            payload = {
                "subsession_id": subsession_id,
                "simsession_number": simsession_number,
            }

            raw_data = self._get_resource("/data/results/lap_chart_data", payload=payload)

        except RuntimeError as error:
            self.print_error("result_lap_chart_data", "RuntimeError", str(error))
            return None

        chunks = self._get_chunks(raw_data["chunk_info"])

        if export:
            filename = f"result_lap_chart_data_{subsession_id}.json"
            self.raw_to_json(filename, chunks)

        return chunks

    def result_lap_data(self, subsession_id=None, simsession_number=0, cust_id=None, team_id=None, export=False):
        """
        Returns a dictionary of the lap data for the given sub session id & either team or user depending.

        link: https://members-ng.iRacing.com/data/results/lap_data
        expirationSeconds:	900

        :param subsession_id: (number) Required
        :param simsession_number: (number) The main event is 0; the preceding event is -1, and so on.
        :param cust_id: (number) Required if the subsession was a single-driver event. Optional for team events.
            If omitted for a team event then the laps driven by all the team's drivers will be included.
        :param team_id: (number) Required if the subsession was a team event.
        :param export: (boolean) should the file be exported to JSON
        :return: dict All data retrieved is returned.
        """

        if not subsession_id:
            raise RuntimeError("Please supply a subsession_id")

        try:
            # Subsession is required and simsession allows us to specify which sim event we want.
            payload = {
                "subsession_id": subsession_id,
                "simsession_number": simsession_number,
            }

            # Team events require team_id but cust_id is optional
            if team_id:
                payload["team_id"] = team_id
                if cust_id:
                    payload["cust_id"] = self.get_cust_id(cust_id)

            # If it's not a team event then cust_id is required.
            else:
                payload["cust_id"] = self.get_cust_id(cust_id)

            # Make the call
            raw_data = self._get_resource("/data/results/lap_data", payload=payload)
            chunks = self._get_chunks(raw_data["chunk_info"])

        except RuntimeError as error:
            self.print_error("result_lap_data", "RuntimeError", str(error))
            return None

        if export:
            filename = f"result_lap_data_{subsession_id}.json"
            self.raw_to_json(filename, chunks)

        return chunks

    # search_hosted - to be tested
    def result_search_hosted(self, start_range_begin=None, start_range_end=None, finish_range_begin=None,
                             finish_range_end=None, cust_id=None, host_cust_id=None, session_name=None, league_id=None,
                             league_season_id=None, car_id=None, track_id=None, category_ids=None, export=False):

        """

        Hosted and league sessions.
        Maximum time frame of 90 days. Results split into one or more files with chunks of results.
        For scraping results the most effective approach is to keep track of the maximum end_time found during a
        search then make the subsequent call using that date/time as the finish_range_begin and skip any subsessions
        that are duplicated.  Results are ordered by subsessionid which is a proxy for start time.
        Requires one of: start_range_begin, finish_range_begin.
        Requires one of: cust_id, host_cust_id, session_name.
        link: https://members-ng.iRacing.com/data/results/search_hosted
        expirationSeconds: in 900
        :param start_range_begin: string - Session start times. ISO-8601 UTC time zero offset: 2022-04-01T15:45Z.
        :param start_range_end: string - ISO-8601 UTC time zero offset: 2022-04-01T15:45Z. Exclusive.
        May be omitted if start_range_begin is less than 90 days in the past.
        :param finish_range_begin: string - Session finish times. ISO-8601 UTC time zero offset: 2022-04-01T15:45Z.
        :param finish_range_end: string - ISO-8601 UTC time zero offset: 2022-04-01T15:45Z. Exclusive.
        May be omitted if finish_range_begin is less than 90 days in the past.
        :param cust_id: number - The participant's customer ID.
        :param host_cust_id: number - The host's customer ID.
        :param session_name: string - Part or all of the session's name.
        :param league_id: number - Include only results for the league with this ID.
        :param league_season_id: number - Include only results for the league season with this ID.
        :param car_id: number - One of the cars used by the session.
        :param track_id: number - The ID of the track used by the session.
        :param category_ids: numbers - Track categories to include in the search.  Defaults to all. ?category_ids=1,2,3,4
        :param export: (boolean) - export to json
        :return:
        """
        try:

            # Default to 90 days ago if no date set
            if not (start_range_begin or finish_range_begin):
                tod = datetime.datetime.now()
                d = datetime.timedelta(days=30)
                start_range_begin = (tod - d).replace(second=0).replace(microsecond=0).replace(tzinfo=datetime.timezone.utc).isoformat()

            if not (cust_id or host_cust_id):
                raise RuntimeError("Please supply either cust_id or host_cust_id")

            params = locals()
            payload = {}
            for x in params.keys():
                if x != "self" and params[x]:
                    payload[x] = params[x]

            raw_data = self._get_resource("/data/results/search_hosted", payload=payload)
            chunks = self._get_chunks(raw_data["data"]["chunk_info"])

        except RuntimeError as e:
            print("Check Resource call", str(e))
            return None

        if export:
            filename = "result_search_hosted.json"
            self.raw_to_json(filename, chunks)

        return chunks

    # search_series - to be tested
    def result_search_series(self, season_year=None, season_quarter=None,
                             start_range_begin=None, start_range_end=None, finish_range_begin=None, finish_range_end=None,
                             cust_id=None, team_id=None, series_id=None, race_week_num=None,
                             official_only=True, event_types=None, category_ids=None, export=False):
        """
        Official series. Maximum time frame of 90 days. Results split into one or more files with chunks of results.
        For scraping results the most effective approach is to keep track of the maximum end_time found during a search
        then make the subsequent call using that date/time as the finish_range_begin and skip any subsessions that are
        duplicated.

        Results are ordered by subsessionid which is a proxy for start time but groups together multiple splits of a
        series when multiple series launch sessions at the same time.

        Requires at least one of: season_year and season_quarter, start_range_begin, finish_range_begin.
        :param season_year: (number) Required when using season_quarter.
        :param season_quarter: (number) Required when using season_year.
        :param start_range_begin: (string) Session start times. ISO-8601 UTC time zero offset: "2022-04-01T15:45Z"
        :param start_range_end: (string) ISO-8601 UTC time zero offset: "2022-04-01T15:45Z".
        Exclusive. May be omitted if start_range_begin is less than 90 days in the past.
        :param finish_range_begin: (string) Session finish times. ISO-8601 UTC time zero offset: "2022-04-01T15:45Z
        :param finish_range_end: (string) ISO-8601 UTC time zero offset: "2022-04-01T15:45Z".
        Exclusive. May be omitted if finish_range_begin is less than 90 days in the past
        :param cust_id: (number) Include only sessions in which this customer participated. Ignored if team_id is supplied."
        :param team_id: (number) Include only sessions in which this team participated. Takes priority over cust_id if both are supplied.
        :param series_id: (number) Include only sessions for series with this ID.
        :param race_week_num: (number) Include only sessions with this race week number.
        :param official_only: (boolean) If true, include only sessions earning championship points. Defaults to all.
        :param event_types: (numbers) Types of events to include in the search. Defaults to all. ?event_types=2,3,4,5
        :param category_ids: (numbers) License categories to include in the search.  Defaults to all. ?category_ids=1,2,3,4
        :param export: (boolean) should the file be exported to JSON
        :return:
        """
        try:

            # Default to 90 days ago if no date set
            if not (start_range_begin or finish_range_begin):
                tod = datetime.datetime.now()
                d = datetime.timedelta(days=30)
                start_range_begin = (tod - d).replace(second=0).replace(microsecond=0).replace(tzinfo=datetime.timezone.utc).isoformat()

            if not cust_id:
                raise RuntimeError("Please supply either cust_id or host_cust_id")

            params = locals()
            payload = {}
            for x in params.keys():
                if x != "self" and params[x]:
                    payload[x] = params[x]

            raw_data = self._get_resource("/data/results/search_hosted", payload=payload)
            chunks = self._get_chunks(raw_data["data"]["chunk_info"])

        except RuntimeError as e:
            print("Check Resource call", str(e))
            return None

        if export:
            filename = "result_search_hosted.json"
            self.raw_to_json(filename, chunks)

        return chunks

    def result_season_results(self, season_id=None, event_type=None, race_week_num=None, export=False):
        """

        Returns all the races that have occurred for a given series (using its season_id) allowing access
        to the subsession_id.

        link: https://members-ng.iracing.com/data/results/season_results
        expirationSeconds:	900

        :param season_id: (number) Required
        :param event_type: (number) Restrict to one event type: 2 - Practice; 3 - Qualify; 4 - Time Trial; 5 - Race
        :param race_week_num: (number) The first race week of a season is 0.
        :param export: (boolean) should the file be exported to JSON
        :return:
        """
        try:
            if not season_id:
                raise RuntimeError("Please supply a ta_comp_season_id")
            payload = {"season_id": season_id, "event_type": event_type, "race_week_num": race_week_num}
            raw_data = self._get_resource("/data/results/season_results", payload=payload)

        except RuntimeError as error:
            self.print_error("result_season_results", "RuntimeError", str(error))
            return None

        if export:
            filename = f"season_results_{season_id}_{race_week_num}_{event_type}.json"
            self.raw_to_json(filename, raw_data)

        return raw_data

    ##### SEASON #####
    def get_season_list(self, season_year, season_quarter, export=False):
        """
        Returns a dictionary of the series available for the season_year and quarter provided.

        link: https://members-ng.iRacing.com/data/season/list
        expirationSeconds:	900

        :param season_year: (number) Required
        :param season_quarter: (number) Required
        :param export: (boolean) should the file be exported to JSON
        :return: dict All data retrieved is returned.
        """
        try:
            payload = {"season_year": season_year, "season_quarter": season_quarter}
            raw_data = self._get_resource("/data/season/list", payload=payload)

        except RuntimeError as error:
            self.print_error("get_season_list", "RuntimeError", str(error))
            return None

        if export:
            filename = f"season_list_{season_year}{season_quarter}.json"
            self.raw_to_json(filename, raw_data)

        return raw_data

    def season_race_guide(self, from_date=None, include_end_after_from=False, export=False):
        """
        Returns a dictionary of the races available for the given from date.
        If no date is given it defaults to the current date.
        suitable date retrieved with datetime.datetime.now().replace(microsecond=0).isoformat()

        link: https://members-ng.iracing.com/data/season/race_guide
        expirationSeconds: 900

        :param from_date: ISO-8601 (2024-06-11T05:53:00Z) offset format. Defaults to the current time.
        :param include_end_after_from:
        Include sessions with start times up to 3 hours after this time.
        Times in the past will be rewritten to the current time.

        :param export: (boolean) should the file be exported to JSON
        :return: dict All data retrieved is returned.
        """

        try:
            payload = {"from_date": from_date, "include_end_after_from": include_end_after_from}
            raw_data = self._get_resource("/data/season/race_guide", payload=payload)

        except RuntimeError as error:
            self.print_error("season_race_guide", "RuntimeError", str(error))
            return None

        if export:
            if from_date:
                from_date_file = "_" + from_date.replace('-', '').replace(':', '')
            else:
                from_date_file = ""
            filename = f"season_race_guide{from_date_file}.json"
            self.raw_to_json(filename, raw_data)

        return raw_data

    # spectator_subsessionids - to be added
    # spectator_subsessionids_detail - to be added

    ##### SERIES #####
    def get_series_assets(self, export=False):
        """
        Gets all the extended assets (images, text copy and logos) associated with active series
        image paths are relative to https://images-static.iRacing.com/

        link:	https://members-ng.iRacing.com/data/series/assets
        expirationSeconds: 900

        :param export: (boolean) should the file be exported to JSON
        :return: dictionary
        """
        try:
            raw_data = self._get_resource("/data/series/assets")

        except RuntimeError as error:
            self.print_error("get_series_assets", "RuntimeError", str(error))
            return None

        if export:
            self.raw_to_json('series_assets.json', raw_data)
        return raw_data

    def get_series(self, export=False):
        """
        Gets summary data, allowed licenses and forum links for all the active series.

        link:	https://members-ng.iRacing.com/data/series/get
        expirationSeconds: 900

        :param export: (boolean) should the file be exported to JSON
        :return: dict All data retrieved is returned.
        """
        try:
            raw_data = self._get_resource("/data/series/get")

        except RuntimeError as error:
            self.print_error("get_series_assets", "RuntimeError", str(error))
            return None

        if export:
            self.raw_to_json('series.json', raw_data)
        return raw_data

    def past_seasons(self, series_id=0, export=False):
        """
        Get all seasons for a series. Filter list by official:true for seasons with standings.

        link:	https://members-ng.iracing.com/data/series/past_seasons
        expirationSeconds:	900

        :param series_id: (number) Required
        :param export: (boolean) should the file be exported to JSON
        :return: dict All data retrieved is returned.
        """
        try:
            payload = {"series_id": series_id}
            raw_data = self._get_resource("/data/series/past_seasons", payload=payload)

        except RuntimeError as error:
            self.print_error("past_seasons", "RuntimeError", str(error))
            return None

        if export:
            filename = f"series_past_seasons_{series_id}.json"
            self.raw_to_json(filename, raw_data)
        return raw_data

    def series_seasons(self, include_series=False, export=False):
        """
        Get all seasons for a series. Filter list by official:true for seasons with standings.
        This appears to be the series for the current seasons with race weeks included.

        link:	https://members-ng.iRacing.com/data/series/seasons
        expirationSeconds:	900

        :param include_series: (boolean)
        :param export: (boolean) should the file be exported to JSON
        :return: dict All data retrieved is returned.
        """
        try:
            payload = {"include_series": include_series}
            raw_data = self._get_resource("/data/series/seasons", payload=payload)

        except RuntimeError as error:
            self.print_error("series_seasons", "RuntimeError", str(error))
            return None

        if export:
            self.raw_to_json("series_seasons.json", raw_data)
        return raw_data

    def series_stats(self, official=False, export=False):
        """

        To get series and seasons for which standings should be available,
        @todo test as the week continues does the data returned change?

        link:	https://members-ng.iRacing.com/data/series/stats_series
        expirationSeconds:	900

        :param official: (boolean) filter the list by official: true.
        :param export: (boolean) should the file be exported to JSON
        :return: dict All data retrieved is returned.
        """
        try:
            payload = {"official": official}
            raw_data = self._get_resource("/data/series/stats_series", payload=payload)

        except RuntimeError as error:
            self.print_error("series_stats", "RuntimeError", str(error))
            return None

        if export:
            self.raw_to_json("series_stats.json", raw_data)
        return raw_data

    ##### STATS #####
    def stats_member_bests(self, cust_id=None, car_id=None, export=False):
        """
        Gets the member's best results for a given car_id.
        If car_id is omitted then a list of available cars is returned.

        link: https://members-ng.iRacing.com/data/stats/member_bests
        expirationSeconds:	900

        :param cust_id: (number) Defaults to the authenticated member.
        :param car_id: (number) First call should exclude car_id; use cars_driven list in return for subsequent calls
        :param export: (boolean) should the file be exported to JSON
        :return:
        """
        cust_id = self.get_cust_id(cust_id)
        try:
            if car_id:
                payload = {"cust_id": cust_id, "car_id": car_id}
                raw_data = self._get_resource("/data/stats/member_bests", payload=payload)
                filename = f"stats_member_bests_{cust_id}_car{car_id}.json"
            else:
                payload = {"cust_id": cust_id}
                raw_data = self._get_resource("/data/stats/member_bests", payload=payload)
                filename = f"stats_member_bests_{cust_id}.json"

        except RuntimeError as error:
            self.print_error("stats_member_bests", "RuntimeError", str(error))
            return None

        if export:
            self.raw_to_json(filename, raw_data)
        return raw_data

    def stats_member_career(self, cust_id=None, export=False):
        """
        Returns a summary dictionary of the member stats for each category

        link:	https://members-ng.iRacing.com/data/stats/member_career
        expirationSeconds:	900

        :param cust_id: (number) Defaults to the authenticated member.
        :param export: (boolean) should the file be exported to JSON
        :return: dict All data retrieved is returned.
        """
        cust_id = self.get_cust_id(cust_id)
        try:
            payload = {"cust_id": cust_id}
            raw_data = self._get_resource("/data/stats/member_career", payload=payload)

        except RuntimeError as error:
            self.print_error("stats_member_career", "RuntimeError", str(error))
            return None

        if export:
            filename = f"stats_member_career_{cust_id}.json"
            self.raw_to_json(filename, raw_data['stats'])
        return raw_data

    def stats_member_division(self, season_id=None, event_type=5, export=False):
        """
        Divisions are 0-based: 0 is Division 1, 10 is Rookie.
        See /data/constants/divisons for more information. Always for the authenticated member.

        @todo Test on working season during the season.

        link:	https://members-ng.iRacing.com/data/stats/member_career
        expirationSeconds:	900

        :param event_type: (number) Required
        :param season_id: (number) Required - The event type code for the division type: 4 - Time Trial; 5 - Race
        :param export: (boolean) should the file be exported to JSON
        :return: dict All data retrieved is returned.
        """
        try:
            payload = {'season_id': season_id, 'event_type': event_type}
            raw_data = self._get_resource("/data/stats/member_division", payload=payload)

        except RuntimeError as error:
            self.print_error("stats_member_division", "RuntimeError", str(error))
            return None

        if export:
            filename = f"stats_member_division.json"
            self.raw_to_json(filename, raw_data)
        return raw_data

    def stats_member_recap(self, cust_id=None, year=None, season=None, export=False):
        """
        Returns the most recent 10 races for the CUST_ID provided.

        link: https://members-ng.iracing.com/data/stats/member_recap
        expirationSeconds: 900

        :param season: Season (quarter) within the year; if not supplied the recap will be for the entire year.
        :param year: Season year; if not supplied the current calendar year (UTC) is used.
        :param cust_id: (number) Defaults to the authenticated member.
        :param export: (boolean) should the file be exported to JSON
        """

        cust_id = self.get_cust_id(cust_id)
        try:
            payload = {"cust_id": cust_id, "year": year, "season": season}
            raw_data = self._get_resource("/data/stats/member_recap", payload=payload)

        except RuntimeError as error:
            self.print_error("stats_member_recap", "RuntimeError", str(error))
            return None

        if export:
            filename = f"stats_member_recap_{cust_id}_{year}{season}.json"
            self.raw_to_json(filename, raw_data)
        return raw_data

    def stats_recent_races(self, cust_id=None, export=False):
        """
        Returns the most recent 10 races for the CUST_ID provided.

        link: https://members-ng.iracing.com/data/stats/member_recent_races
        expirationSeconds: 900

        :param cust_id: (number) Defaults to the authenticated member.
        :param export: (boolean) should the file be exported to JSON
        """

        cust_id = self.get_cust_id(cust_id)
        try:
            payload = {"cust_id": cust_id}
            raw_data = self._get_resource("/data/stats/member_recent_races", payload=payload)

        except RuntimeError as error:
            self.print_error("stats_recent_races", "RuntimeError", str(error))
            return None

        if export:
            filename = f"stats_recent_races_{cust_id}.json"
            self.raw_to_json(filename, raw_data['races'])
        return raw_data

    def stats_member_summary(self, cust_id=None, export=False):
        """
        Returns a summary dictionary of the members stats for the current year

        link: https://members-ng.iracing.com/data/stats/member_summary
        expirationSeconds:	900

        :param cust_id: (number) Defaults to the authenticated member.
        :param export: (boolean) should the file be exported to JSON
        :returns dictionary
        """
        cust_id = self.get_cust_id(cust_id)
        try:
            payload = {"cust_id": cust_id}
            raw_data = self._get_resource("/data/stats/member_summary", payload=payload)

        except RuntimeError as error:
            self.print_error("stats_member_summary", "RuntimeError", str(error))
            return None

        if export:
            filename = f"stats_member_summary_{cust_id}.json"
            self.raw_to_json(filename, raw_data)
        return raw_data

    def stats_member_yearly(self, cust_id=None, export=False):
        """
        Returns a summary dictionary of the member stats for each category
        for every year the driver has been a member.

        link: https://members-ng.iracing.com/data/stats/member_yearly
        expirationSeconds:	900

        :param cust_id: (number) Defaults to the authenticated member.
        :param export: (boolean) should the file be exported to JSON
        """

        cust_id = self.get_cust_id(cust_id)
        try:
            payload = {"cust_id": cust_id}
            raw_data = self._get_resource("/data/stats/member_yearly", payload=payload)

        except RuntimeError as error:
            self.print_error("stats_member_yearly", "RuntimeError", str(error))
            return None

        if export:
            filename = f"stats_member_yearly_{cust_id}.json"
            self.raw_to_json(filename, raw_data['stats'])
        return raw_data

    def season_driver_standings(self, season_id, car_class_id, club_id=None, division=None, race_week_num=None, export=False):
        """

        Gets the driver standings for a particular class within a series in the given season.

        @todo need to process the returned data.  has chunks!

        link: https://members-ng.iracing.com/data/stats/season_driver_standings
        expirationSeconds:	900

        :param season_id: (number) Required
        :param car_class_id: (number) Required
        :param club_id: (number) Defaults to all (-1).
        :param division: (number) Divisions are 0-based: 0 is Division 1, 10 is Rookie.
            See /data/constants/divisons for more information. Defaults to all.
        :param race_week_num: (number) The first race week of a season is 0.
        :param export: (boolean) should the file be exported to JSON
        :return:
        """
        try:

            payload = {"season_id": season_id, "car_class_id": car_class_id, "club_id": club_id, "division": division, "race_week_num": race_week_num}
            raw_data = self._get_resource("/data/stats/season_driver_standings", payload=payload)

        except RuntimeError as error:
            self.print_error("season_driver_standings", "RuntimeError", str(error))
            return None

        if export:
            filename = f"stats_season_driver_standings_{season_id}_{car_class_id}.json"
            self.raw_to_json(filename, raw_data)
        return raw_data

    def season_supersession_standings(self, season_id, car_class_id, club_id=None, division=None, race_week_num=None, export=False):
        """

        Appears to return the standings for a series including drop weeks in a CSV file.

        @todo need to process the returned data.  has chunks!

        link: https://members-ng.iracing.com/data/stats/season_supersession_standings
        expirationSeconds:	900

        :param season_id: (number) Required
        :param car_class_id: (number) Required
        :param club_id: (number) Defaults to all (-1).
        :param division: (number) Divisions are 0-based: 0 is Division 1, 10 is Rookie.
            See /data/constants/divisons for more information. Defaults to all.
        :param race_week_num: (number) The first race week of a season is 0.
        :param export: (boolean) should the file be exported to JSON
        :return:
        """
        try:
            payload = {"season_id": season_id, "car_class_id": car_class_id, "club_id": club_id, "division": division, "race_week_num": race_week_num}
            raw_data = self._get_resource("/data/stats/season_supersession_standings", payload=payload)

        except RuntimeError as error:
            self.print_error("season_supersession_standings", "RuntimeError", str(error))
            return None

        if export:
            filename = f"stats_season_supersession_standings_{season_id}_{car_class_id}.json"
            self.raw_to_json(filename, raw_data)
        return raw_data

    def season_team_standings(self, season_id, car_class_id, race_week_num=None, export=False):
        """

        Appears to return the team standings for a series including drop weeks in a CSV file.

        @todo need to process the returned data.  has chunks!

        link: https://members-ng.iracing.com/data/stats/season_team_standings
        expirationSeconds:	900

        :param season_id: (number) Required
        :param car_class_id: (number) Required
        :param race_week_num: (number) The first race week of a season is 0.
        :param export: (boolean) should the file be exported to JSON
        :return:
        """
        try:
            payload = {"season_id": season_id, "car_class_id": car_class_id, "race_week_num": race_week_num}
            raw_data = self._get_resource("/data/stats/season_team_standings", payload=payload)

        except RuntimeError as error:
            self.print_error("season_team_standings", "RuntimeError", str(error))
            return None

        if export:
            filename = f"stats_season_team_standings_{season_id}_{car_class_id}.json"
            self.raw_to_json(filename, raw_data)
        return raw_data

    def season_tt_standings(self, season_id, car_class_id, club_id=None, division=None, race_week_num=None, export=False):
        """

        Gets the TT (Time trial) driver standings for a particular class within a series in the given season.

        @todo need to process the returned data.  has chunks!

        link: https://members-ng.iracing.com/data/stats/season_tt_standings
        expirationSeconds:	900

        :param season_id: (number) Required
        :param car_class_id: (number) Required
        :param club_id: (number) Defaults to all (-1).
        :param division: (number) Divisions are 0-based: 0 is Division 1, 10 is Rookie.
            See /data/constants/divisons for more information. Defaults to all.
        :param race_week_num: (number) The first race week of a season is 0.
        :param export: (boolean) should the file be exported to JSON
        :return:
        """
        try:

            payload = {"season_id": season_id, "car_class_id": car_class_id, "club_id": club_id, "division": division, "race_week_num": race_week_num}
            raw_data = self._get_resource("/data/stats/season_tt_standings", payload=payload)

        except RuntimeError as error:
            self.print_error("season_tt_standings", "RuntimeError", str(error))
            return None

        if export:
            filename = f"season_tt_standings{season_id}_{car_class_id}.json"
            self.raw_to_json(filename, raw_data)
        return raw_data

    def season_tt_results(self, season_id, car_class_id, race_week_num, club_id=None, division=None, export=False):
        """

        Gets the TT (Time trial) driver results for a particular class within a series in the given season.

        @todo need to process the returned data.  has chunks!

        link: https://members-ng.iracing.com/data/stats/season_tt_results
        expirationSeconds:	900

        :param season_id: (number) Required
        :param car_class_id: (number) Required
        :param race_week_num: (number) Required.  The first race week of a season is 0.
        :param club_id: (number) Defaults to all (-1).
        :param division: (number) Divisions are 0-based: 0 is Division 1, 10 is Rookie.
            See /data/constants/divisons for more information. Defaults to all.

        :param export: (boolean) should the file be exported to JSON
        :return:
        """
        try:

            payload = {"season_id": season_id, "car_class_id": car_class_id, "club_id": club_id, "division": division, "race_week_num": race_week_num}
            raw_data = self._get_resource("/data/stats/season_tt_results", payload=payload)

        except RuntimeError as error:
            self.print_error("season_tt_results", "RuntimeError", str(error))
            return None

        if export:
            filename = f"season_tt_results{season_id}_{car_class_id}.json"
            self.raw_to_json(filename, raw_data)
        return raw_data

    def season_qualify_results(self, season_id, car_class_id, race_week_num, club_id=None, division=None, export=False):
        """

        Gets the qualifying results for a particular class within a series in the given season.

        @todo need to process the returned data.  has chunks!

        link: https://members-ng.iracing.com/data/stats/season_qualify_results
        expirationSeconds:	900

        :param season_id: (number) Required
        :param car_class_id: (number) Required
        :param race_week_num: (number) Required.  The first race week of a season is 0.
        :param club_id: (number) Defaults to all (-1).
        :param division: (number) Divisions are 0-based: 0 is Division 1, 10 is Rookie.
            See /data/constants/divisons for more information. Defaults to all.

        :param export: (boolean) should the file be exported to JSON
        :return:
        """
        try:

            payload = {"season_id": season_id, "car_class_id": car_class_id, "club_id": club_id, "division": division, "race_week_num": race_week_num}
            raw_data = self._get_resource("/data/stats/season_qualify_results", payload=payload)

        except RuntimeError as error:
            self.print_error("season_qualify_results", "RuntimeError", str(error))
            return None

        if export:
            filename = f"season_qualify_results{season_id}_{car_class_id}.json"
            self.raw_to_json(filename, raw_data)
        return raw_data

    def world_records(self, car_id, track_id, season_year=None, season_quarter=None, export=False):
        """

        Gets the qualifying results for a particular class within a series in the given season.

        @todo need to process the returned data.  all tested chunks returned null

        link: https://members-ng.iracing.com/data/stats/world_records
        expirationSeconds:	900


        :param car_id: (number) Required.
        :param track_id: (number) Required.
        :param season_year: (number) Limit best times to a given year
        :param season_quarter: (number) Limit best times to a given quarter; only applicable when year is used
        :param export: (boolean) should the file be exported to JSON
        :return:
        """
        try:

            payload = {"car_id": car_id, "track_id": track_id, "season_year": season_year, "season_quarter": season_quarter}
            raw_data = self._get_resource("/data/stats/world_records", payload=payload)

        except RuntimeError as error:
            self.print_error("world_records", "RuntimeError", str(error))
            return None

        if export:
            filename = f"world_records{car_id}_{track_id}.json"
            self.raw_to_json(filename, raw_data)
        return raw_data

    ##### TEAM #####
    def team_get(self, team_id=None, include_licenses=False, export=False):
        """

        Gets information and roster relating to the team provided.
        @todo How do we get team_ids associated with a driver?

        link: https://members-ng.iRacing.com/data/team/get
        expirationSeconds: 900

        :param team_id: (number) Required
        :param include_licenses: (boolean) For faster responses, only request when necessary.
        :param export: (boolean) should the file be exported to JSON
        :return: dict All data retrieved is returned.
        """
        try:
            if not team_id:
                raise RuntimeError("Please supply a team_id")

            payload = {"team_id": team_id, "include_licenses": include_licenses}
            raw_data = self._get_resource("/data/team/get", payload=payload)

        except RuntimeError as error:
            self.print_error("team_get", "RuntimeError", str(error))
            return None

        if export:
            self.raw_to_json(f"team_{team_id}.json", raw_data)
        return raw_data

    ##### TIME ATTACK #####
    # member_season_results - untested
    def member_season_results(self, ta_comp_season_id=None, export=True):
        """
        Results for the authenticated member, if any

        link: https://members-ng.iracing.com/data/time_attack/member_season_results
        expirationSeconds: 900

        :param ta_comp_season_id: (number) Required
        :param export: (boolean) should the file be exported to JSON
        :return: dict All data retrieved is returned.
        """
        try:
            if not ta_comp_season_id:
                raise RuntimeError("Please supply a ta_comp_season_id")

            payload = {"ta_comp_season_id": ta_comp_season_id}
            raw_data = self._get_resource("/data/time_attack/member_season_results", payload=payload)

        except RuntimeError as error:
            self.print_error("member_season_results", "RuntimeError", str(error))
            return None

        if export:
            self.raw_to_json(f"member_season_results_{ta_comp_season_id}.json", raw_data)
        return raw_data

    ##### TRACK #####
    def get_track_assets(self, export=False):
        """
        Gets the extended copy and image links etc. associated with the tracks.
        Image paths are relative to https://images-static.iRacing.com/

        link:	https://members-ng.iRacing.com/data/track/assets
        expirationSeconds:	900

        :param export: (boolean) should the file be exported to JSON
        :return: dict All data retrieved is returned.
        """
        try:
            raw_data = self._get_resource("/data/track/assets")

        except RuntimeError as error:
            self.print_error("get_track_assets", "RuntimeError", str(error))
            return None

        if export:
            self.raw_to_json('track_assets.json', raw_data)
        return raw_data

    def get_tracks(self, export=False):
        """

        link:	https://members-ng.iRacing.com/data/track/get
        expirationSeconds:	900
        :param export: (boolean) export to json.
        :return:
        """
        try:
            raw_data = self._get_resource("/data/track/get")
            self.get_track_assets(export)

        except RuntimeError as error:
            self.print_error("get_track_assets", "RuntimeError", str(error))
            return None

        if export:
            self.raw_to_json('tracks.json', raw_data)
        return raw_data


##### RUNNING THIS As A STANDALONE SCRIPT #####
if __name__ == '__main__':

    # This is so I can import settings from my parent application.
    # You will want to comment this out and replace the arguments below with your own.
    from iRaceEngineer import settings

    # Create an instance of the ir_client
    ir_client = RacingClient(settings.USERNAME, settings.PASSWORD, settings.CUSTID, settings.BASE_DIR, settings.FILE_FOLDER)

    ##### CARS #####
    # car_assets = ir_client.get_car_assets(export=True) # Tested 12/06/2024
    # car = ir_client.get_car(export=True) # Tested 12/06/2024

    ##### CAR CLASS #####
    # car_class = ir_client.get_carclass(export=True) # Tested 12/06/2024

    ##### CONSTANTS #####
    # categories = ir_client.get_categories(export=True) # Tested 12/06/2024
    # divisions = ir_client.get_divisions(export=True) # Tested 12/06/2024
    # event_types = ir_client.get_event_types(export=True) # Tested 12/06/2024

    ##### DRIVER STATS BY CATEGORY - need to revisit this #####
    # driver_cat_stats = ir_client.driver_stats_by_category(export=False)

    ##### HOSTED #####
    # hosted_combined_sessions = ir_client.hosted_combined_sessions(export=True) # Tested 12/06/2024
    # hosted_sessions = ir_client.hosted_sessions(export=True) # Tested 12/06/2024

    ##### LEAGUE #####
    # cust_league_sessions =ir_client.league_cust_league_sessions(export=True) # Tested 12/06/2024
    # league_directory = ir_client.get_league_directory(restrict_to_member=True, export=True) # Tested 12/06/2024
    # league = ir_client.league_get(league_id=10725, export=True) # Tested 12/06/2024
    # points = ir_client.league_get_points_systems(league_id=10725, export=True) # Tested 12/06/2024
    # league_membership - need to revisit this.
    # roster = ir_client.league_roster(league_id=10725, export=True) # Tested 12/06/2024
    # league_seasons = ir_client.league_seasons(league_id=10725, retired=True, export=True) # Tested 12/06/2024
    # season_standings = ir_client.league_season_standings(league_id=10725, season_id=101283, export=True) # Tested 12/06/2024
    # season_sessions = ir_client.league_season_sessions(league_id=10725, season_id=101283, export=True) # Tested 12/06/2024

    ##### LOOKUP #####
    # club_history = ir_client.lookup_club_history(season_quarter=2, season_year=2024, export=True) # Tested 12/06/2024
    # countries = ir_client.lookup_countries(export=True) # Tested 12/06/2024
    # drivers = ir_client.lookup_drivers(search_term="Chris Max Davies", export=True) # Tested 12/06/2024
    # lookup_get - need to revisit this.
    # licenses = ir_client.lookup_licenses(export=True) # Tested 12/06/2024

    ##### MEMBER #####
    # awards = ir_client.member_awards(cust_id=903845, export=True) # Tested 10/06/2024
    # chart_data = ir_client.member_chart_data(export=True) # Tested 10/06/2024
    # member = ir_client.member_get(cust_id=903845, export=True) # Tested 10/06/2024
    # info = ir_client.member_info(export=True) # Tested 10/06/2024
    # participation_credits = ir_client.member_participation_credits(export=True) # Tested 10/06/2024
    # profile = ir_client.member_profile(export=True) # Tested 10/06/2024

    ##### RESULTS #####
    # result = ir_client.results_get(subsession_id=68837306, export=True) # Tested 10/06/2024
    # result_event = ir_client.result_event_log(subsession_id=68837306, export=True) # Tested 10/06/2024
    # result_chart = ir_client.result_lap_chart_data(subsession_id=68837306, export=True) # Tested 11/06/2024
    # result_lap_data = ir_client.result_lap_data(subsession_id=68837306, export=True) # Tested 11/06/2024
    # search_hosted - to be tested
    # search_series - to be tested
    # season_results = ir_client.result_season_results(season_id=4906, event_type=5, race_week_num=0, export=True) # Tested 13/06/2024

    ##### SEASON #####
    # season_list = ir_client.get_season_list(season_year=2024, season_quarter=3, export=True) # Tested 11/06/2024
    # race_guide = ir_client.season_race_guide(export=True) # Tested 11/06/2024
    # spectator_subsessionids - to be added
    # spectator_subsessionids_detail - to be added

    ##### SERIES #####
    # series_assets = ir_client.get_series_assets(export=True) # Tested 11/06/2024
    # series = ir_client.get_series(export=True) # Tested 11/06/2024
    # series_past_seasons = ir_client.past_seasons(series_id=520, export=True) # Tested 11/06/2024
    # series_seasons = ir_client.series_seasons(export=True) # Tested 11/06/2024
    # series_stats = ir_client.series_stats(export=True) # Tested 11/06/2024

    ##### STATS #####
    # ir_client.stats_member_bests(export=True) # Tested 11/06/2024
    # bests = ir_client.stats_member_bests(car_id=128, export=True) # Tested 11/06/2024
    # career = ir_client.stats_member_career(export=True) # Tested 11/06/2024
    # division = ir_client.stats_member_division(season_id=4957, export=True) # Further Testing Required
    # recap = ir_client.stats_member_recap(cust_id=903845, export=True) # Tested 12/06/2024
    # races = ir_client.stats_recent_races(cust_id=903845, export=True) # Tested 12/06/2024
    # member_summary = ir_client.stats_member_summary(cust_id=903845, export=True) # Tested 12/06/2024
    # yearly = ir_client.stats_member_yearly(cust_id=903845, export=True) # Tested 12/06/2024
    # driver_standings = ir_client.season_driver_standings(4900, 4011, export=True) # Tested 13/06/2024 - Needs completing.
    # super_session_standings = ir_client.season_supersession_standings(4900, 4011, export=True) # Tested 13/06/2024 - Needs completing.
    # team_standings = ir_client.season_team_standings(4900, 4011, export=True) # Needs revisiting.
    # tt_standings = ir_client.season_tt_standings(4900, 4011, export=True) # Tested 13/06/2024 - Needs completing.
    # tt_results = ir_client.season_tt_results(4900, 4011, 0, export=True) # Tested 13/06/2024 - Needs completing.
    # qualify_results = ir_client.season_qualify_results(4900, 4011, 0, export=True) # Tested 13/06/2024 - Needs completing.
    # world_records = ir_client.world_records(160, 486, export=True) # Tested 13/06/2024 - Needs completing.

    ##### TEAM #####
    # team = ir_client.team_get(team_id=319141, export=True) # Tested 12/06/2024

    ##### TRACK #####
    # track_assets = ir_client.get_track_assets(export=True) # Tested 12/06/2024
    # tracks = ir_client.get_tracks(export=True) # Tested 12/06/2024
