# Display Manager

import time
import displayio
import terminalio
from adafruit_display_text.label import Label
from adafruit_bitmap_font import bitmap_font

cwd = ("/" + __file__).rsplit("/", 1)[0]

icon_spritesheet = cwd + "/bmp/weather-icons.bmp"
icon_width = 16
icon_height = 16

# custom font for temperature trend indicators
symbol_font = bitmap_font.load_font("/bdf/custom_bellota.bdf")

# custom colors hex codes
metro_orange = 0xf06a37
metro_red = 0xda1b30
metro_green = 0x49742a

# custom scroll delay for scroll_text
scroll_delay = 0.03

class display_manager(displayio.Group):
    def __init__(
            self,
            display,
    ):
        super().__init__()
        self.display = display
        # set up label groups
        self.root_group = displayio.Group()
        self.root_group.append(self)

        # create scrolling notification group
        self._scrolling_group = displayio.Group()
        # hide scrolling group by default
        self._scrolling_group.hidden = True
        self.append(self._scrolling_group)

        # create parent weather group for weather display groups
        self._weather_group = displayio.Group()
        self._weather_group.hidden = False
        self.append(self._weather_group)

        # create current weather icon group
        # TODO center icon on 16x16 top-left segment
        self._icon_group = displayio.Group(x=4, y=2)
        self._weather_group.append(self._icon_group)

        # create current temperature group
        self._current_temp_group = displayio.Group()
        self._weather_group.append(self._current_temp_group)

        # create temperature trend symbol group
        self._temp_trend_group = displayio.Group()
        self._weather_group.append(self._temp_trend_group)

        # create min max temperature group
        self._min_max_temp_group = displayio.Group()
        self._weather_group.append(self._min_max_temp_group)

        # create parent train group for train Labels
        self._train_board_group = displayio.Group()
        self._train_board_group.hidden = False
        self.append(self._train_board_group)

        # set default column and row measurements (NOTE: default config is 1)
        self.col1 = 4
        self.col2 = 28
        self.col25 = 52
        self.col3 = 108
        self.row1 = 8
        self.row2 = 24

        # Load the icon sprite sheet
        icons = displayio.OnDiskBitmap(open(icon_spritesheet, "rb"))
        self._icon_sprite = displayio.TileGrid(
            icons,
            pixel_shader=getattr(icons, 'pixel_shader', displayio.ColorConverter()),
            tile_width=icon_width,
            tile_height=icon_height
        )

        # set current temperature text
        # left-middle column, top row
        self.temp_text = Label(terminalio.FONT)
        self.temp_text.x = self.col2 - 4
        self.temp_text.y = self.row1
        self.temp_text.color = 0xFFFFFF
        self._current_temp_group.append(self.temp_text)

        # set current temperature trend icon
        self.temp_trend_icon = Label(font=symbol_font)
        self.temp_trend_icon.x = self.col2 + 8
        self.temp_trend_icon.y = self.row1 - 7
        self._temp_trend_group.append(self.temp_trend_icon)

        # set daily minimum temperature text
        # left column, bottom row
        self.min_temp_text = Label(terminalio.FONT)
        self.min_temp_text.x = self.col1 + 2
        self.min_temp_text.y = self.row2
        self.min_temp_text.color = 0x1e81b0
        self._min_max_temp_group.append(self.min_temp_text)

        # set daily maximum temperature text
        # left-middle column, bottom row
        self.max_temp_text = Label(terminalio.FONT)
        self.max_temp_text.x = self.col2 - 4
        self.max_temp_text.y = self.row2
        self.max_temp_text.color = metro_red
        self._min_max_temp_group.append(self.max_temp_text)

        # set top row of train destination text
        # right-middle column, top row
        self.top_row_train_text = Label(terminalio.FONT)
        self.top_row_train_text.x = self.col25
        self.top_row_train_text.y = self.row1
        self.top_row_train_text.color = metro_orange
        self.top_row_train_text.text = "Shady Gr"
        self._train_board_group.append(self.top_row_train_text)

        # set top row of train time to arrival text
        # right column, top row
        self.top_row_train_min = Label(terminalio.FONT)
        self.top_row_train_min.x = self.col3
        self.top_row_train_min.y = self.row1
        self.top_row_train_min.color = metro_orange
        self.top_row_train_min.text = "0"
        self._train_board_group.append(self.top_row_train_min)

        # set bottom row of train destination text
        # right-middle column, bottom row
        self.bottom_row_train_text = Label(terminalio.FONT)
        self.bottom_row_train_text.x = self.col25
        self.bottom_row_train_text.y = self.row2
        self.bottom_row_train_text.color = metro_orange
        self.bottom_row_train_text.text = "Glenmont"
        self._train_board_group.append(self.bottom_row_train_text)

        # set bottom row of train time to arrival text
        # right column, bottom row
        self.bottom_row_train_min = Label(terminalio.FONT)
        self.bottom_row_train_min.x = self.col3
        self.bottom_row_train_min.y = self.row2
        self.bottom_row_train_min.color = metro_orange
        self.bottom_row_train_min.text = "0"
        self._train_board_group.append(self.bottom_row_train_min)

        # create scrolling label (top row by default)
        self.scrolling_label = Label(terminalio.FONT)
        self.scrolling_label.x = 0
        self.scrolling_label.y = self.row1
        self.scrolling_label.color = 0xFFFFFF
        self._scrolling_group.append(self.scrolling_label)

        # default icon set to none
        self.set_icon(None)

    def set_icon(self, icon_name):
        """Use icon_name to get the position of the sprite and update
        the current icon.
        :param icon_name: The icon name returned by openweathermap
        Format is always 2 numbers followed by 'd' or 'n' as the 3rd character
        """
        icon_map = ("01", "02", "03", "04", "09", "10", "11", "13", "50")
        if self._icon_group:
            self._icon_group.pop()
        if icon_name is not None:
            row = None
            for index, icon in enumerate(icon_map):
                if icon == icon_name[0:2]:
                    row = index
                    break
            column = 0
            if icon_name[2] == "n":
                column = 1
            if row is not None:
                self._icon_sprite[0] = (row * 2) + column
                self._icon_group.append(self._icon_sprite)

    # helper function to assign color to minutes labels
    def get_minutes_color(self, minutes):
        try:
            if minutes == "ARR" or minutes == "BRD":
                return metro_red
            else:
                return metro_orange
        except ValueError as e:
            print("Value Error: {}".format(e))
            return metro_orange

    # update temperature text, trend, and max/min
    # input is a weather dict and configuration number
    def update_weather(self, weather):
        if weather:
            # set the icon
            self.set_icon(weather["icon"])

            # set the temperature
            self.temp_text.text = "%d" % weather["current_temp"]
            self.min_temp_text.text = "%d" % weather["daily_temp_min"]
            self.max_temp_text.text = "%d" % weather["daily_temp_max"]

            # set temperature trend
            # if the temperature change is more than 1 degree
            temp_diff_default = 1
            temp_diff = weather["hourly_next_temp"] - weather["current_temp"]
            if temp_diff > 0 and temp_diff > temp_diff_default:
                # print("trending higher by {}".format(temp_diff))
                # comma is increase arrow
                self.temp_trend_icon.text = ","
                self.temp_trend_icon.color = metro_red
                self.temp_trend_icon.y = self.row1 - 6
                self._temp_trend_group.hidden = False

            elif temp_diff < 0 and abs(temp_diff) > temp_diff_default:
                # print("trending lower by {}".format(abs(temp_diff)))
                # period is decrease arrow
                self.temp_trend_icon.text = "."
                self.temp_trend_icon.color = 0x1e81b0
                self.temp_trend_icon.y = self.row1 - 6
                self._temp_trend_group.hidden = False

            else:
                # print("no trend at {}".format(temp_diff))
                self._temp_trend_group.hidden = True
        else:
            self.temp_text.text = "..."

    # update train destination text and time to arrival
    # input is a list of train objects and display config integer
    def assign_trains(self, trains, historical_trains):
        try:
            if trains[0] is not None:
                self.top_row_train_text.text = trains[0].destination

                # if train isn't Shady Grove, set train text color to white
                if trains[0].destination_code is not "A15":
                    self.top_row_train_text.color = 0xFFFFFF
                else:
                    self.top_row_train_text.color = self.get_minutes_color(trains[0].minutes)

                # set min and min text colors
                self.top_row_train_min.text = trains[0].minutes
                self.top_row_train_min.color = self.get_minutes_color(trains[0].minutes)
            # no A train data
            elif historical_trains[0] is not None:
                self.top_row_train_text.text = "Shady Gr"
                self.top_row_train_min.text = historical_trains[0].minutes
                self.top_row_train_min.color = 0xFFFFFF
            else:
                self.top_row_train_min.text = "NULL"

            if trains[1] is not None:
                self.bottom_row_train_text.text = trains[1].destination

                # if train isn't Glenmont, set train text color to white
                if trains[1].destination_code is not "B11":
                    self.bottom_row_train_text.color = 0xFFFFFF
                else:
                    self.bottom_row_train_text.color = self.get_minutes_color(trains[1].minutes)

                # set min and min text colors
                self.bottom_row_train_min.text = trains[1].minutes
                self.bottom_row_train_min.color = self.get_minutes_color(trains[1].minutes)
            # no B train data
            elif historical_trains[1] is not None:
                self.bottom_row_train_text.text = "Glenmont"
                self.bottom_row_train_min.text = historical_trains[1].minutes
                self.bottom_row_train_min.color = 0xFFFFFF
            else:
                self.bottom_row_train_min.text = "NULL"

        except TypeError as e:
            print(e)

    def scroll_text(self, label_text, row):
        self._scrolling_group.x = self.display.width
        if row is 1:
            self._scrolling_group.y = self.row1
        else:
            self._scrolling_group.y = self.row2
        self.scrolling_label.text = label_text
        self._weather_group.hidden = True
        self._train_board_group.hidden = True
        self._scrolling_group.hidden = False

        for _ in range(self.display.width * 3.5):
            self._scrolling_group.x = self._scrolling_group.x - 1
            time.sleep(scroll_delay)
        self._scrolling_group.hidden = True
        self._weather_group.hidden = False
        self._train_board_group.hidden = False
        self.refresh_display()

    # refresh the root group on the display
    def refresh_display(self):
        self.display.show(self.root_group)