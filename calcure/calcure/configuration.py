"""This module creates and loads user config file"""

import argparse
import configparser
import sys
import os
import logging
import datetime
from pathlib import Path

from calcure.data import AppState


def _build_arg_parser():
    parser = argparse.ArgumentParser(
        prog="calcure",
        description="TUI calendar and task manager",
    )
    parser.add_argument("-v", "--version", action="version", version="%(prog)s 3.4")
    parser.add_argument("-j", help="start on journal page", action="store_true")
    parser.add_argument("-d", help="start on daily view", action="store_true")
    parser.add_argument("-w", help="start on weekly view", action="store_true")
    parser.add_argument("-p", help="enable privacy mode", action="store_true")
    parser.add_argument("-i", help="use Persian calendar", action="store_true")
    parser.add_argument("--folder", help="folder with data files", metavar="PATH")
    parser.add_argument("--config", help="path to config file", metavar="PATH")
    parser.add_argument("--task", help="add a task and exit", metavar="NAME")
    parser.add_argument("--event", help="add an event and exit (format: YYYY-MM-DD-name)", metavar="DATE-NAME")
    parser.add_argument("--json", help="output events as JSON", action="store_true")
    parser.add_argument("--month", help="target month for JSON output (YYYY-MM)", metavar="YYYY-MM")
    parser.add_argument("--add", help="add an event non-interactively", metavar="TITLE")
    parser.add_argument("--date", help="event date for --add (YYYY-MM-DD)", metavar="YYYY-MM-DD")
    parser.add_argument("--time", help="event time for --add (HH:MM or HH:MM-HH:MM)", metavar="TIME")
    return parser


_args = None


def get_args():
    global _args
    if _args is None:
        _args, _ = _build_arg_parser().parse_known_args()
    return _args


class Config:
    """User configuration loaded from the config.ini file"""
    def __init__(self):
        self.home_path = Path.home()
        self.calcurse_todo_file = self.home_path / ".local" / "share" / "calcurse" / "todo"
        self.calcurse_events_file = self.home_path / ".local" / "share" / "calcurse" / "apts"
        self.config_folder = self.home_path / ".config" / "calcure"
        self.config_file = self.config_folder / "config.ini"
        self.log_file = self.config_folder / "info.log"
        self.is_first_run= True

        # Create config folder:
        self.config_folder.mkdir(exist_ok=True)

        # Read config file:
        self.create_config_file()
        self.read_config_file_from_user_arguments()
        self.read_config_file()
        self.read_parameters_from_user_arguments()


    def shorten_path(self, path):
        """Replace home part of paths with tilde"""
        if str(path).startswith(str(self.home_path)):
            return str(path).replace(str(self.home_path), "~", 1)
        else:
            return str(path)


    def create_config_file(self):
        """Create config.ini file if it does not exist"""

        if self.config_file.exists():
            self.is_first_run = False
            return

        conf = configparser.ConfigParser()
        conf["Parameters"] = {
                "folder_with_datafiles":     self.shorten_path(self.config_folder),
                "calcurse_todo_file":        self.shorten_path(self.calcurse_todo_file),
                "calcurse_events_file":      self.shorten_path(self.calcurse_events_file),
                "log_file":                  self.shorten_path(self.log_file),
                "language":                  "en",
                "default_view":              "calendar",
                "default_calendar_view":     "monthly",
                "birthdays_from_abook":      "No",
                "show_keybindings":          "Yes",
                "privacy_mode":              "No",
                "show_weather":              "No",
                "weather_city":              "",
                "weather_metric_units":      "Yes",
                "minimal_today_indicator":   "Yes",
                "minimal_days_indicator":    "Yes",
                "minimal_weekend_indicator": "Yes",
                "show_calendar_borders":     "No",
                "show_week_numbers":        "No",
                "show_moon_phases":          "No",
                "cut_titles_by_cell_length": "No",
                "ask_confirmations":         "Yes",
                "ask_confirmation_to_quit":  "Yes",
                "use_unicode_icons":         "Yes",
                "use_24_hour_format":        "Yes",
                "show_current_time":         "No",
                "show_holidays":             "Yes",
                "colorize_holidays_date":    "Yes",
                "hide_done_tasks":           "No",
                "hidden_done_count":         "Yes",
                "show_nothing_planned":      "Yes",
                "one_timer_at_a_time":       "No",
                "holiday_country":           "UnitedStates",
                "use_persian_calendar":      "No",
                "start_week_day":            "1",
                "weekend_days":              "6,7",
                "refresh_interval":          "1",
                "data_reload_interval":      "0",
                "split_screen":              "Yes",
                "inverse_daily_scroll":      "No",
                "right_pane_percentage":     "25",
                "journal_header":            "JOURNAL",
                "event_icon":                "•",
                "privacy_icon":              "•",
                "today_icon":                "•",
                "birthday_icon":             "★",
                "holiday_icon":              "⛱",
                "hidden_icon":               "...",
                "done_icon":                 "✔",
                "todo_icon":                 "•",
                "important_icon":            "‣",
                "separator_icon":            "│",
                "deadline_icon":             "⚑",
                }

        default_user = os.environ.get("USER", "user")
        conf["radicale"] = {
                "enabled":   "Yes",
                "url":       f"http://127.0.0.1:5232/{default_user}/",
                "username":  default_user,
                "password":  "",
                "calendar":  "Official",
                }

        conf["Colors"] = {
                "color_today":           "3",
                "color_events":          "7",
                "color_days":            "7",
                "color_day_names":       "8",
                "color_weekends":        "7",
                "color_weekend_names":   "8",
                "color_hints":           "8",
                "color_prompts":         "3",
                "color_confirmations":   "1",
                "color_birthdays":       "3",
                "color_holidays":        "8",
                "color_holidays_date":   "8",
                "color_todo":            "7",
                "color_done":            "8",
                "color_title":           "3",
                "color_calendar_header": "3",
                "color_important":       "3",
                "color_unimportant":     "8",
                "color_timer":           "3",
                "color_timer_paused":    "8",
                "color_time":            "7",
                "color_deadlines":       "1",
                "color_weather":         "3",
                "color_active_pane":     "3",
                "color_separator":       "8",
                "color_calendar_border": "8",
                "color_frame":           "8",
                "color_ics_calendars":   "3,7,8,1,3,7,8,1,3,7",
                "color_foreground":      "7",
                "color_background":      "-1",
                }

        conf["Styles"] = {
                "bold_today":               "No",
                "bold_days":                "No",
                "bold_day_names":           "No",
                "bold_holidays":            "No",
                "bold_weekends":            "No",
                "bold_weekend_names":       "No",
                "bold_title":               "No",
                "bold_active_pane":         "No",
                "underlined_today":         "No",
                "underlined_days":          "No",
                "underlined_day_names":     "No",
                "underlined_holidays":      "No",
                "underlined_weekends":      "No",
                "underlined_weekend_names": "No",
                "underlined_title":         "No",
                "underlined_active_pane":   "No",
                "strikethrough_done":       "No",
                }

        conf["Event icons"] = {
                "travel":      "✈",
                "plane":       "✈",
                "voyage":      "✈",
                "flight":      "✈",
                "airport":     "✈",
                "trip":        "🏕",
                "vacation":    "⛱",
                "holiday":     "⛱",
                "day-off":     "⛱",
                "hair":        "✂",
                "barber":      "✂",
                "beauty":      "✂",
                "nails":       "✂",
                "game":        "♟",
                "match":       "♟",
                "play":        "♟",
                "interview":   "🎙️",
                "conference":  "🎙️",
                "talk":        "🎙️",
                "dating":      "♥",
                "concert":     "♪",
                "dance":       "♪",
                "music":       "♪",
                "rehearsal":   "♪",
                "call":        "🕻",
                "zoom":        "🕻",
                "deadline":    "⚑",
                "over":        "⚑",
                "finish":      "⚑",
                "end":         "⚑",
                "doctor":      "✚",
                "dentist":     "✚",
                "medical":     "✚",
                "hospital":    "✚",
                "party":       "☘",
                "bar":         "☘",
                "museum":      "⛬",
                "meet":        "⛬",
                "sport":       "⛷",
                "gym":         "🏋",
                "training":    "⛷",
                "email":       "✉",
                "letter":      "✉",
                }

        with open(self.config_file, 'w', encoding="utf-8") as f:
            conf.write(f)


    def read_config_file(self):
        """Read user config.ini file and assign values to all the global variables"""
        try:
            conf = configparser.ConfigParser()
            conf.read(self.config_file, 'utf-8')

            # Reading default view:
            default_view = conf.get("Parameters", "default_view", fallback="calendar")
            if default_view == 'journal':
                self.DEFAULT_VIEW = AppState.JOURNAL
            else:
                self.DEFAULT_VIEW = AppState.CALENDAR

            # Calendar settings:
            self.SHOW_KEYBINDINGS          = conf.getboolean("Parameters", "show_keybindings", fallback=True)
            self.MINIMAL_TODAY_INDICATOR   = conf.getboolean("Parameters", "minimal_today_indicator", fallback=True)
            self.MINIMAL_DAYS_INDICATOR    = conf.getboolean("Parameters", "minimal_days_indicator", fallback=True)
            self.MINIMAL_WEEKEND_INDICATOR = conf.getboolean("Parameters", "minimal_weekend_indicator", fallback=True)
            self.ASK_CONFIRMATIONS         = conf.getboolean("Parameters", "ask_confirmations", fallback=True)
            self.ASK_CONFIRMATION_TO_QUIT  = conf.getboolean("Parameters", "ask_confirmation_to_quit", fallback=True)
            self.SHOW_WEATHER              = conf.getboolean("Parameters", "show_weather", fallback=False)
            self.SHOW_CURRENT_TIME         = conf.getboolean("Parameters", "show_current_time", fallback=False)
            self.DISPLAY_ICONS             = conf.getboolean("Parameters", "use_unicode_icons", fallback=True)
            self.USE_24_HOUR_FORMAT        = conf.getboolean("Parameters", "use_24_hour_format", fallback=True)
            self.DISPLAY_HOLIDAYS          = conf.getboolean("Parameters", "show_holidays", fallback=True)
            self.COLORIZE_HOLIDAYS_DATE    = conf.getboolean("Parameters", "colorize_holidays_date", fallback=True)
            self.PRIVACY_MODE              = conf.getboolean("Parameters", "privacy_mode", fallback=False)
            self.CUT_TITLES                = conf.getboolean("Parameters", "cut_titles_by_cell_length", fallback=False)
            self.BIRTHDAYS_FROM_ABOOK      = conf.getboolean("Parameters", "birthdays_from_abook", fallback=True)
            self.SPLIT_SCREEN              = conf.getboolean("Parameters", "split_screen", fallback=True)
            self.INVERSE_DAILY_SCROLL      = conf.getboolean("Parameters", "inverse_daily_scroll", fallback=False)
            self.SHOW_NOTHING_PLANNED      = conf.getboolean("Parameters", "show_nothing_planned", fallback=True)
            self.SHOW_CALENDAR_BORDERS     = conf.getboolean("Parameters", "show_calendar_borders", fallback=False)
            self.SHOW_WEEK_NUMBERS         = conf.getboolean("Parameters", "show_week_numbers", fallback=False)
            self.SHOW_MOON_PHASES          = conf.getboolean("Parameters", "show_moon_phases", fallback=False)
            self.USE_PERSIAN_CALENDAR      = conf.getboolean("Parameters", "use_persian_calendar", fallback=False)
            self.LANG                      = conf.get("Parameters", "language", fallback="en")
            self.START_WEEK_DAY            = int(conf.get("Parameters", "start_week_day", fallback=1))
            self.WEEKEND_DAYS              = conf.get("Parameters", "weekend_days", fallback="6,7")
            self.WEEKEND_DAYS              = [int(i) for i in self.WEEKEND_DAYS.split(",")]
            self.HOLIDAY_COUNTRY           = conf.get("Parameters", "holiday_country", fallback="UnitedStates")
            self.WEATHER_CITY              = conf.get("Parameters", "weather_city", fallback="")
            self.WEATHER_METRIC_UNITS      = conf.getboolean("Parameters", "weather_metric_units", fallback=True)
            self.DEFAULT_CALENDAR_VIEW     = conf.get("Parameters", "default_calendar_view", fallback="monthly")
            self.LOG_FILE                  = conf.get("Parameters", "log_file", fallback=self.log_file)
            self.LOG_FILE                  = Path(self.LOG_FILE).expanduser()

            # Journal settings:
            self.CALCURSE_TODO_FILE = conf.get("Parameters", "calcurse_todo_file", fallback=self.calcurse_todo_file)
            self.CALCURSE_TODO_FILE = Path(self.CALCURSE_TODO_FILE).expanduser()


            self.CALCURSE_EVENTS_FILE = conf.get("Parameters", "calcurse_events_file", fallback=self.calcurse_events_file)
            self.CALCURSE_EVENTS_FILE = Path(self.CALCURSE_EVENTS_FILE).expanduser()

            self.JOURNAL_HEADER        = conf.get("Parameters", "journal_header", fallback="JOURNAL")
            self.SHOW_KEYBINDINGS      = conf.getboolean("Parameters", "show_keybindings", fallback=True)
            self.HIDE_DONE_TASKS       = conf.getboolean("Parameters", "hide_done_tasks", fallback=False)
            self.HIDDEN_DONE_COUNT     = conf.getboolean("Parameters", "hidden_done_count", fallback=True)
            self.DONE_ICON             = conf.get("Parameters", "done_icon", fallback="✔") if self.DISPLAY_ICONS else "×"
            self.TODO_ICON             = conf.get("Parameters", "todo_icon", fallback="•") if self.DISPLAY_ICONS else "·"
            self.IMPORTANT_ICON        = conf.get("Parameters", "important_icon", fallback="‣") if self.DISPLAY_ICONS else "!"
            self.REFRESH_INTERVAL      = int(conf.get("Parameters", "refresh_interval", fallback=1))
            self.DATA_RELOAD_INTERVAL  = int(conf.get("Parameters", "data_reload_interval", fallback=0))
            self.RIGHT_PANE_PERCENTAGE = int(conf.get("Parameters", "right_pane_percentage", fallback=25))
            self.ONE_TIMER_AT_A_TIME   = conf.getboolean("Parameters", "one_timer_at_a_time", fallback=False)

            # ICS files:
            self.ICS_EVENT_FILES = conf.get("Parameters", "ics_event_files", fallback=None, raw=True)
            if self.ICS_EVENT_FILES is not None:
                self.ICS_EVENT_FILES = [str(i) for i in self.ICS_EVENT_FILES.split(",")]

            self.ICS_TASK_FILES = conf.get("Parameters", "ics_task_files", fallback=None, raw=True)
            if self.ICS_TASK_FILES is not None:
                self.ICS_TASK_FILES = [str(i) for i in self.ICS_TASK_FILES.split(",")]

            # Radicale CalDAV settings:
            default_user = os.environ.get("USER", "user")
            default_url  = f"http://127.0.0.1:5232/{default_user}/"
            rad_sec = "radicale" if conf.has_section("radicale") else ("Radicale" if conf.has_section("Radicale") else None)
            if rad_sec:
                self.RADICALE_ENABLED   = conf.getboolean(rad_sec, "enabled", fallback=True)
                self.RADICALE_URL       = os.environ.get("RADICALE_URL", conf.get(rad_sec, "url", fallback=default_url))
                self.RADICALE_USERNAME  = os.environ.get("RADICALE_USERNAME", conf.get(rad_sec, "username", fallback=default_user))
                self.RADICALE_PASSWORD  = os.environ.get("RADICALE_PASSWORD", conf.get(rad_sec, "password", fallback=""))
                self.RADICALE_CALENDAR  = os.environ.get("RADICALE_CALENDAR", conf.get(rad_sec, "calendar", fallback="Official"))
            else:
                self.RADICALE_ENABLED   = True
                self.RADICALE_URL       = os.environ.get("RADICALE_URL", default_url)
                self.RADICALE_USERNAME  = os.environ.get("RADICALE_USERNAME", default_user)
                self.RADICALE_PASSWORD  = os.environ.get("RADICALE_PASSWORD", "")
                self.RADICALE_CALENDAR  = os.environ.get("RADICALE_CALENDAR", "Official")

            # Soft TUI Base16 ANSI Default Palette (0-15 and -1 transparent bg):
            col_sec = "Colors" if conf.has_section("Colors") else ("colors" if conf.has_section("colors") else None)
            def _getcolor(key, default):
                if col_sec:
                    return int(conf.get(col_sec, key, fallback=default))
                return default

            # Calendar colors:
            self.COLOR_TODAY           = _getcolor("color_today", 3)
            self.COLOR_EVENTS          = _getcolor("color_events", 7)
            self.COLOR_DAYS            = _getcolor("color_days", 7)
            self.COLOR_DAY_NAMES       = _getcolor("color_day_names", 8)
            self.COLOR_WEEKENDS        = _getcolor("color_weekends", 7)
            self.COLOR_WEEKEND_NAMES   = _getcolor("color_weekend_names", 8)
            self.COLOR_HINTS           = _getcolor("color_hints", 8)
            self.COLOR_PROMPTS         = _getcolor("color_prompts", 3)
            self.COLOR_BIRTHDAYS       = _getcolor("color_birthdays", 3)
            self.COLOR_HOLIDAYS        = _getcolor("color_holidays", 8)
            self.COLOR_HOLIDAYS_DATE   = _getcolor("color_holidays_date", 8)
            self.COLOR_DEADLINES       = _getcolor("color_deadlines", 1)
            self.COLOR_CONFIRMATIONS   = _getcolor("color_confirmations", 1)
            self.COLOR_TIMER           = _getcolor("color_timer", 3)
            self.COLOR_TIMER_PAUSED    = _getcolor("color_timer_paused", 8)
            self.COLOR_TIME            = _getcolor("color_time", 7)
            self.COLOR_WEATHER         = _getcolor("color_weather", 3)
            self.COLOR_FOREGROUND      = _getcolor("color_foreground", 7)
            self.COLOR_BACKGROUND      = _getcolor("color_background", -1)
            self.COLOR_CALENDAR_HEADER = _getcolor("color_calendar_header", 3)
            self.COLOR_ACTIVE_PANE     = _getcolor("color_active_pane", 3)
            self.COLOR_SEPARATOR       = _getcolor("color_separator", 8)
            self.COLOR_CALENDAR_BORDER = _getcolor("color_calendar_border", 8)
            self.COLOR_FRAME           = _getcolor("color_frame", 8)
            self.COLOR_ICS_CALENDARS   = conf.get(col_sec, "color_ics_calendars", fallback="3,7,8,1") if col_sec else "3,7,8,1"
            self.COLOR_ICS_CALENDARS   = [int(number) for number in self.COLOR_ICS_CALENDARS.split(",")]

            # Journal colors:
            self.COLOR_TODO           = _getcolor("color_todo", 7)
            self.COLOR_DONE           = _getcolor("color_done", 8)
            self.COLOR_TITLE          = _getcolor("color_title", 3)
            self.COLOR_IMPORTANT      = _getcolor("color_important", 3)
            self.COLOR_UNIMPORTANT    = _getcolor("color_unimportant", 8)

            # Font styles:
            self.BOLD_TODAY               = conf.getboolean("Styles", "bold_today", fallback=False)
            self.BOLD_DAYS                = conf.getboolean("Styles", "bold_days", fallback=False)
            self.BOLD_DAY_NAMES           = conf.getboolean("Styles", "bold_day_names", fallback=False)
            self.BOLD_HOLIDAYS            = conf.getboolean("Styles", "bold_holidays", fallback=False)
            self.BOLD_WEEKENDS            = conf.getboolean("Styles", "bold_weekends", fallback=False)
            self.BOLD_WEEKEND_NAMES       = conf.getboolean("Styles", "bold_weekend_names", fallback=False)
            self.BOLD_TITLE               = conf.getboolean("Styles", "bold_title", fallback=False)
            self.BOLD_ACTIVE_PANE         = conf.getboolean("Styles", "bold_active_pane", fallback=False)
            self.UNDERLINED_TODAY         = conf.getboolean("Styles", "underlined_today", fallback=False)
            self.UNDERLINED_DAYS          = conf.getboolean("Styles", "underlined_days", fallback=False)
            self.UNDERLINED_DAY_NAMES     = conf.getboolean("Styles", "underlined_day_names", fallback=False)
            self.UNDERLINED_HOLIDAYS      = conf.getboolean("Styles", "underlined_holidays", fallback=False)
            self.UNDERLINED_WEEKENDS      = conf.getboolean("Styles", "underlined_weekends", fallback=False)
            self.UNDERLINED_WEEKEND_NAMES = conf.getboolean("Styles", "underlined_weekend_names", fallback=False)
            self.UNDERLINED_TITLE         = conf.getboolean("Styles", "underlined_title", fallback=False)
            self.UNDERLINED_ACTIVE_PANE   = conf.getboolean("Styles", "underlined_active_pane", fallback=False)
            self.STRIKETHROUGH_DONE       = conf.getboolean("Styles", "strikethrough_done", fallback=False)

            # Icons:
            self.TODAY_ICON       = conf.get("Parameters", "today_icon", fallback="•") if self.DISPLAY_ICONS else "·"
            self.PRIVACY_ICON     = conf.get("Parameters", "privacy_icon", fallback="•") if self.DISPLAY_ICONS else "·"
            self.HIDDEN_ICON      = conf.get("Parameters", "hidden_icon", fallback="...")
            self.EVENT_ICON       = conf.get("Parameters", "event_icon", fallback="•") if self.DISPLAY_ICONS else "·"
            self.BIRTHDAY_ICON    = conf.get("Parameters", "birthday_icon", fallback="★") if self.DISPLAY_ICONS else "·"
            self.HOLIDAY_ICON     = conf.get("Parameters", "holiday_icon", fallback="☘️") if self.DISPLAY_ICONS else "·"
            self.SEPARATOR_ICON   = conf.get("Parameters", "separator_icon", fallback="│")
            self.DEADLINE_ICON    = conf.get("Parameters", "deadline_icon", fallback="⚑") if self.DISPLAY_ICONS else "·"
            try:
                self.ICONS = {word: icon for (word, icon) in conf.items("Event icons")}
            except configparser.NoSectionError:
                self.ICONS = {}

            self.data_folder = conf.get("Parameters", "folder_with_datafiles", fallback=self.config_folder)
            self.data_folder = Path(self.data_folder).expanduser()
            self.EVENTS_FILE = self.data_folder / "events.csv"
            self.TASKS_FILE = self.data_folder / "tasks.csv"

        except Exception:
            ERR_FILE1 = "Looks like there is a problem in your config.ini file. Perhaps you edited it and entered a wrong line. "
            ERR_FILE2 = "Try removing your config.ini file and run the program again, it will create a fresh working config file."
            logging.error(ERR_FILE1 + ERR_FILE2)
            exit()


    def read_config_file_from_user_arguments(self):
        """Read user config.ini location from user arguments"""
        args = get_args()
        if args.config:
            self.config_file = Path(args.config).expanduser()
            if not self.config_file.exists():
                self.create_config_file()

    def read_parameters_from_user_arguments(self):
        """Read user arguments that were provided at the run. These values take priority over config.ini"""
        args = get_args()
        if args.folder:
            self.data_folder = Path(args.folder).expanduser()
            self.data_folder.mkdir(exist_ok=True)
            self.EVENTS_FILE = self.data_folder / "events.csv"
            self.TASKS_FILE = self.data_folder / "tasks.csv"
        if args.p:
            self.PRIVACY_MODE = True
        if args.j:
            self.DEFAULT_VIEW = AppState.JOURNAL
        if args.d:
            self.DEFAULT_VIEW = AppState.CALENDAR
            self.DEFAULT_CALENDAR_VIEW = "daily"
        if args.w:
            self.DEFAULT_VIEW = AppState.CALENDAR
            self.DEFAULT_CALENDAR_VIEW = "weekly"
        if args.i:
            self.USE_PERSIAN_CALENDAR = True

