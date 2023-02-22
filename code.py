from adafruit_display_text import label
from adafruit_bitmap_font import bitmap_font
import board
import displayio
import framebufferio
import rgbmatrix
import terminalio
import gc
import time
import busio
from digitalio import DigitalInOut, Pull
import neopixel
import adafruit_apds9960.apds9960
from adafruit_apds9960 import colorutility
from adafruit_debouncer import Debouncer
from adafruit_matrixportal.matrix import Matrix
import adafruit_requests as requests
from adafruit_esp32spi import adafruit_esp32spi
from adafruit_esp32spi import adafruit_esp32spi_wifimanager
import display_manager

# --- SENSOR SETUP -------
try:
    i2c = busio.I2C(board.SCL, board.SDA)
    sensor = adafruit_apds9960.apds9960.APDS9960(i2c)
    sensor.enable_color = True
    sensor_enabled=True
    # light sensor defaults and counters
    lux=0
    lux_counter=0
    #NOTE: Change lux_min to at least XX to enable light sensing mode
    lux_min=-100
    night_mode=False
except:
    print("no sensor attached")
    sensor_enabled=False

# --- CONSTANTS SETUP ----

try:
    from secrets import secrets
except ImportError:
    print("Wifi + constants are kept in secrets.py, please add them there!")
    raise

# local Metro station
station_code = secrets["station_code"]
historical_trains = [None, None]

# width of total displays in pixels
# NOTE this width is set for 2 64x32 RGB LED Matrix panels
# (https://www.adafruit.com/product/2278)
width = 128

# daily highest temperature
# max_temp, day of the year
highest_temp = [None,None]
# daily lowest temperature
# min_temp, day of the year
lowest_temp = [None, None]
# current temperature
# current_temp, time.time()
current_temp = [None, None]

# timezone offset from OpenWeather response
timezone_offset = None

# --- INITIALIZE DISPLAY -----------------------------------------------

# MATRIX DISPLAY MANAGER
matrix = Matrix(width=128, height=32, bit_depth=2, tile_rows=1)
display_manager = display_manager.display_manager(matrix.display)
print("display manager loaded")

# --- WIFI SETUP -------------
# Initialize ESP32 Pins:
esp32_cs = DigitalInOut(board.ESP_CS)
esp32_ready = DigitalInOut(board.ESP_BUSY)
esp32_reset = DigitalInOut(board.ESP_RESET)
# Initialize wifi components
spi = busio.SPI(board.SCK, board.MOSI, board.MISO)
esp = adafruit_esp32spi.ESP_SPIcontrol(spi, esp32_cs, esp32_ready, esp32_reset)
# Initialize neopixel status light
status_light = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.2)
# Initialize wifi object
wifi = adafruit_esp32spi_wifimanager.ESPSPI_WiFiManager(esp, secrets, status_light)

print("WiFi loaded")

gc.collect()
#print("Point 1 available memory: {} bytes".format(gc.mem_free()))

# --- CLASSES ---

class Train:
    def __init__(self, destination, destination_name, destination_code, minutes):
        self.destination = destination
        self.destination_name = destination_name
        self.destination_code = destination_code
        self.minutes = minutes

# --- FUNCTIONS ---

# queries WMATA API to return a dict with all unique train destinations, sorted by min
# input is StationCode from WMATA API
def get_trains(StationCode, historical_trains):
    try:
        # query WMATA API with input StationCode
        URL = 'https://api.wmata.com/StationPrediction.svc/json/GetPrediction/'
        payload = {'api_key': secrets['wmata api key']}
        response = wifi.get(URL + StationCode, headers=payload)
        json_data = response.json()
    except OSError as e:
        print("Failed to get data, retrying\n", e)
        wifi.reset()
    except RuntimeError as e:
        print("Failed to get data, retrying\n", e)
        wifi.reset()

    # set up two train directions (A station code and B station code)
    A_train=None
    B_train=None
    # check trains in json response for correct destination code prefixes
    try:
        for item in json_data['Trains']:
            # if no train and destination code prefix matches, add
            if item['DestinationCode'][0] is "A" and A_train is None:
                A_train = Train(item['Destination'], item['DestinationName'], item['DestinationCode'], item['Min'])
            elif item['DestinationCode'][0] is "B" and B_train is None:
                B_train = Train(item['Destination'], item['DestinationName'], item['DestinationCode'], item['Min'])
            # if both trains have a train object, pass
            else:
                pass

    except NameError as e:
        print(e)
        print ("No trains returned from WMATA API.")
        pass

    except TypeError as e:
        print(e)
        print ("No trains returned from WMATA API.")
        pass

    # merge train objects into trains array
    # NOTE: None objects accepted, handled by update_trains function in display_manager.py
    trains=[A_train,B_train]
    # if train objects exist in trains array, add them to historical trains
    if A_train is not None:
        historical_trains[0] = A_train
    if B_train is not None:
        historical_trains[1] = B_train
    # print train data
    try:
        for item in Trains:
            print("{} {}: {}".format(item.destination_code, item.destination_name, item.minutes))
    except:
        pass
    return trains

# queries Openweather API to return a dict with current and 3 hr forecast weather data
# input is latitude and longitude coordinates for weather location
def get_weather(lat, long):
    weather_data = {}
    try:
        # query Openweather for weather at location defined by input lat, long
        base_URL = 'https://api.openweathermap.org/data/3.0/onecall?'
        latitude = lat
        longitude = long
        units = 'imperial'
        api_key = secrets['openweather api key']
        exclude = 'minutely,alerts'
        response = wifi.get(base_URL
        +'lat='+latitude
        +'&lon='+longitude
        +'&exclude='+exclude
        +'&units='+units
        +'&appid='+api_key
        )
        weather_json = response.json()

        # insert icon and current weather data into dict
        weather_data["icon"] = weather_json["current"]["weather"][0]["icon"]
        weather_data["current_temp"] = weather_json["current"]["temp"]
        weather_data["current_feels_like"] = weather_json["current"]["feels_like"]
        # insert daily forecast min and max temperature into dict
        weather_data["daily_temp_min"] = weather_json["daily"][0]["temp"]["min"]
        weather_data["daily_temp_max"] = weather_json["daily"][0]["temp"]["max"]
        # insert next hour + 1 forecast temperature and feels like into dict
        weather_data["hourly_next_temp"] = weather_json["hourly"][2]["temp"]
        weather_data["hourly_feels_like"] = weather_json["hourly"][2]["feels_like"]
        # insert UTC data into dict
        weather_data["dt"] = weather_json["current"]["dt"]

        # set timezone offset
        global timezone_offset
        if timezone_offset is None:
            timezone_offset = weather_json["timezone_offset"]

        # grab time from weather response, add timezone offset
        current_time = check_time(weather_data["dt"], timezone_offset)

        # set daily highest temperature
        global highest_temp
        # if daily highest temperature hasn't been set or is from a previous day
        if highest_temp[0] is None or highest_temp[1] != current_time.tm_wday:
            highest_temp[0] = weather_data["daily_temp_max"]
            highest_temp[1] = current_time.tm_wday
            print("Daily highest temp set to {}".format(highest_temp[0]))
        # if daily highest temp is current but less than existing highest temp
        elif highest_temp[0] < weather_data["daily_temp_max"]:
            highest_temp[0] = weather_data["daily_temp_max"]
            print("Daily highest temp set to {}".format(highest_temp[0]))

        # set daily lowest temperature
        global lowest_temp
        # if daily lowest temperature hasn't been set or is from a previous day
        if lowest_temp[0] is None or lowest_temp[1] != current_time.tm_wday:
            lowest_temp[0] = weather_data["daily_temp_min"]
            lowest_temp[1] = current_time.tm_wday
            print("Daily lowest temp set to {}".format(lowest_temp[0]))
        # if daily lowest temp is current but more than existing lowest temp
        elif lowest_temp[0] > weather_data["daily_temp_min"]:
            lowest_temp[0] = weather_data["daily_temp_min"]
            print("Daily lowest temp set to {}".format(lowest_temp[0]))

        # set current temperature every 10 minutes
        if current_temp [0] is None or current_temp[1] - time.time() > 10 * 60:
            current_temp[0] = weather_data["current_temp"]
            current_temp[1] = time.time()
            print("Current temp set to: {}".format(current_temp[0]))

        # clean up response
        del response

        # return dict with relevant data
        return weather_data

    except OSError as e:
        print("Failed to get data, retrying\n", e)
        wifi.reset()
    except RuntimeError as e:
        print("Failed to get data, retrying\n", e)
        wifi.reset()
    except:
        # use past data in case of bad response
        weather_data["current_temp"] = current_temp[0]
        weather_data["daily_temp_max"] = highest_temp[0]
        weather_data["daily_temp_min"] = lowest_temp[0]
        print("historical weather data used.")

def check_sensor(sensor):
    # input is APDS9960 sensor
    # let the sensor come online
    while not sensor.color_data_ready:
        time.sleep(1)
    # get color data from the sensor to calculate lux
    r, g, b, c = sensor.color_data
    lux_curr = round(colorutility.calculate_lux(r, g, b), 1)
    # modify global lux variables based on current lux value
    global lux
    lux = lux_curr

def check_time (dt, timezone_offset):
    utc = time.struct_time(time.localtime(dt))
    offset_utc = time.mktime(utc) + timezone_offset
    return time.localtime(offset_utc)

def check_open(current_time, shut_off_hour):
    # input UTC and timezone offset from Openweather API, override shut off hour
    # output False if Metro has not YET opened (only checks opening, not closing)

    # SET OPENING TIME
    # current day is M-F and time is before 5
    if current_time.tm_wday <= 4 and current_time.tm_hour < 5:
        print("Metro closed: M-F before 5 | D{} H{}".format(current_time.tm_wday, current_time.tm_hour))
        return False

    # current day is Sat/Sun and time is before 7
    elif current_time.tm_wday > 4 and current_time.tm_hour < 7:
        print("Metro closed: Sat/Sun before 7| D{} H{}".format(current_time.tm_wday, current_time.tm_hour))
        return False

    #SET CLOSING TIME
    # Check current hour against shut_off_hour (10PM default, passed in function)
    elif current_time.tm_hour > shut_off_hour:
        print("Metro closed: after 10PM, currently {}".format(current_time.tm_hour))
        return False

    # no closing conditions are met, Metro is open
    else:
        #print("Metro is open")
        return True

# --- OPERATING LOOP ------------------------------------------

# TODO shift all function mgmt to weather_code style with checks and faster loop repetition
loop_counter=1
last_weather_check=None
last_train_check=None
last_plane_check=None

while True:

    # on start, get weather data
    if loop_counter is 1:
        weather = get_weather(secrets['dc coords x'], secrets['dc coords y'])
        gc.collect()
        last_weather_check = time.time()
        print("weather updated: {}".format(weather))

    current_timer = time.time()
    # update weather in ten minute intervals
    if current_timer - last_weather_check > 10 * 60:
        # update weather data
        weather = get_weather(secrets['dc coords x'], secrets['dc coords y'])
        gc.collect()
        last_weather_check = time.time()
        print("weather updated: {}".format(weather))
    else:
        print("weather updated {} seconds ago.".format(time.time() - last_weather_check))

    # update train data on sleep intervals (default: 15 seconds)
    trains = get_trains(station_code, historical_trains)

    # run garbage collection
    gc.collect()

    # update weather display component
    display_manager.update_weather(weather)
    # update train display component
    display_manager.assign_trains(trains, historical_trains)
    display_manager.refresh_display()
    # print available memory
    print("Loop {} available memory: {} bytes".format(loop_counter, gc.mem_free()))

    # increment loop and sleep for 15 seconds
    loop_counter+=1
    time.sleep(15)
