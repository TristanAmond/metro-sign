from adafruit_display_text import label
from adafruit_bitmap_font import bitmap_font
import board
import gc
import time
import busio
from digitalio import DigitalInOut, Pull
import neopixel
import json
import adafruit_apds9960.apds9960
from adafruit_apds9960 import colorutility
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
historical_planes = {}

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
# current temp (for historical)
current_temp = []

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

# --- CLASSES ---

class Train:
    def __init__(self, destination, destination_name, destination_code, minutes):
        self.destination = destination
        self.destination_name = destination_name
        self.destination_code = destination_code
        self.minutes = minutes

class Plane:
    def __init__(self, flight, alt_geom, lat, lon):
        self.flight = flight
        self.alt_geom = alt_geom
        self.lat = lat
        self.lon = lon
        self.location = (lat, lon)
        self.emergency = None

    def get_location(self):
        return self.location

# --- FUNCTIONS ---

# queries WMATA API to return a dict with all unique train destinations, sorted by min
# input is StationCode from WMATA API
def get_trains(StationCode, historical_trains):
    try:
        # query WMATA API with input StationCode
        URL = 'https://api.wmata.com/StationPrediction.svc/json/GetPrediction/'
        payload = {'api_key': secrets['wmata api key']}
        response = requests.get(URL + StationCode, headers=payload)
        json_data = response.json()
    except Exception as e:
        print("Failed to get data, retrying\n", e)
        wifi.reset()

    # set up two train directions (A station code and B station code)
    A_train=None
    B_train=None
    # check trains in json response for correct destination code prefixes
    try:
        for item in json_data['Trains']:
            if item['Line'] is not "RD":
                pass
            # if no train and destination code prefix matches, add
            if item['DestinationCode'][0] is "A" and A_train is None:
                A_train = Train(item['Destination'], item['DestinationName'], item['DestinationCode'], item['Min'])
            elif item['DestinationCode'][0] is "B" and B_train is None:
                B_train = Train(item['Destination'], item['DestinationName'], item['DestinationCode'], item['Min'])
            # if both trains have a train object, pass
            else:
                pass

    except Exception as e:
        print ("Error accessing the WMATA API: ", e)
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
        for item in trains:
            print("{} {}: {}".format(item.destination_code, item.destination_name, item.minutes))
    except:
        pass
    return trains

# queries local ADS-B reciever with dump1090-fa installed for flight data
# adds unseen flights to the plane array
# input is plane array
def get_planes(historical_planes):
    # set local variables
    plane_counter = 0
    planes = {}
    json_dump = None
    # request plane.json from local ADS-B receiver (default location for dump1090-fa)
    try:
        response = wifi.get("http://{}/tar1090/data/aircraft.json".format(secrets['ip_address']))
        json_dump = response.json()
    except Exception as e:
        print("Failed to get data, retrying\n", e)
        wifi.reset()
    gc.collect()

    if json_dump:
    # iterate through each aircraft entry
        for entry in json_dump["aircraft"]:
            # if flight callsign exists
            if "flight" in entry:
                try:
                    new_plane = Plane(entry["flight"].strip(), entry["alt_geom"], entry["lat"], entry["lon"])
                    # seperate emergency field as optional
                    if "emergency" in entry:
                        new_plane.emergency = entry["emergency"]
                    # add to planes dict and increment counter
                    planes[new_plane.flight] = new_plane
                    # add to historical plane dict if not already there
                    if entry["flight"].strip() not in historical_planes:
                        historical_planes[new_plane.flight] = new_plane
                        plane_counter+=1
                except:
                    print("couldn't add plane?")

    purge_planes()
    print("found {} new planes | {} total planes".format(plane_counter, len(historical_planes)))
    return planes

def purge_planes():
    global historical_planes
    if len(historical_planes) >= 100:
        historical_planes.clear()

#TODO separate daily highest_lowest into new function
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

        current_time = check_time()

        # set daily highest temperature
        global highest_temp
        # if daily highest temperature hasn't been set or is from a previous day
        if highest_temp[0] is None or highest_temp[1] != current_time["wday"]:
            highest_temp[0] = weather_data["daily_temp_max"]
            highest_temp[1] = current_time["wday"]
            print("Daily highest temp set to {}".format(highest_temp[0]))
        # if stored highest temp is less than new highest temp
        elif highest_temp[0] < weather_data["daily_temp_max"]:
            highest_temp[0] = weather_data["daily_temp_max"]
            print("Daily highest temp set to {}".format(highest_temp[0]))
        # if stored highest temp is greater than new highest temp
        elif highest_temp[0] > weather_data["daily_temp_max"]:
            weather_data["daily_temp_max"] = highest_temp[0]
            print("Daily highest temp pulled from historical data")

        # set daily lowest temperature
        global lowest_temp
        # if daily lowest temperature hasn't been set or is from a previous day
        if lowest_temp[0] is None or lowest_temp[1] != current_time["wday"]:
            lowest_temp[0] = weather_data["daily_temp_min"]
            lowest_temp[1] = current_time["wday"]
            print("Daily lowest temp set to {}".format(lowest_temp[0]))
        # if daily lowest temp is greater than new lowest temp
        elif lowest_temp[0] > weather_data["daily_temp_min"]:
            lowest_temp[0] = weather_data["daily_temp_min"]
            print("Daily lowest temp set to {}".format(lowest_temp[0]))
        # if daily lowest temp is less than new lowest temp
        elif lowest_temp[0] < weather_data["daily_temp_min"]:
            weather_data["daily_temp_min"] = lowest_temp[0]
            print("Daily lowest temp pulled from historical data")

        # add current temp to historical array
        global current_temp
        current_temp.append(weather_data["current_temp"])
        # clean up response
        del response

        # return dict with relevant data
        return weather_data

    except Exception as e:
        print("Failed to get data, retrying\n", e)
        wifi.reset()

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

    # returns weekday, hour, and minute
def check_time():
    base_url = "http://io.adafruit.com/api/v2/{}/integrations/time/struct?".format(secrets["aio_username"])
    api_key = "X-AIO-Key=" + secrets["aio_key"]
    try:
        time_struct = wifi.get(base_url + api_key)
        time_json= time_struct.json()
    except Exception as e:
        print(e)
        wifi.reset()
    return (time_json)

def check_open(current_time, shut_off_hour):
    # SET OPENING TIME
    # current day is Sat/Sun and time is before 7
    if current_time["hour"] <= 7 and (current_time["wday"] < 7 or current_time["wday"] is 0):
        print("Metro closed: Sat/Sun before 7| D{} H{}".format(
        current_time["wday"], current_time["hour"]
        ))
        return False
    # current day is M-F and time is before 5
    else:
        if current_time["hour"] < 5:
            print("Metro closed: M-F before 5 | D{} H{}".format(
            current_time["wday"], current_time["hour"]
            ))
            return False

    #SET CLOSING TIME
    # Check current hour against shut_off_hour (10PM default, passed in function)
    if current_time["hour"] >= shut_off_hour:
        print("Metro closed: after 10PM, currently {}:{}".format(
        current_time["hour"], current_time["min"]
        ))
        return False

    return True

# --- OPERATING LOOP ------------------------------------------
# TODO use requests.Session() to open a session at the beginning of any function check
# and use the same session for any valid requests
loop_counter=1
last_weather_check=None
last_train_check=None
last_plane_check=None
day_mode=True

while True:
    current_time = check_time()
    try:
        day_mode = check_open(current_time, 22)
        display_manager.night_mode_toggle(day_mode)
    except Exception as e:
        print("Expection: {}".format(e))
        pass

    if day_mode is True:
        # fetch weather data on start and every 10 minutes
        if last_weather_check is None or time.monotonic() > last_weather_check + 60 * 10:
            weather = get_weather(secrets['dc coords x'], secrets['dc coords y'])
            last_weather_check = time.monotonic()
            print("weather updated")
            # update weather display component
            display_manager.update_weather(weather)

        # update train data (default: 15 seconds)
        if last_train_check is None or time.monotonic() > last_train_check + 15:
            trains = get_trains(station_code, historical_trains)
            last_train_check = time.monotonic()
            # update train display component
            display_manager.assign_trains(trains, historical_trains)

        # update plane data (default: 60 seconds)
        if last_plane_check is None or time.monotonic() > last_plane_check + 60:
            planes = get_planes(historical_planes)
            last_plane_check = time.monotonic()

        # display top plane data every 100 loops
        # TODO find closest plane and display when within a certain distance
        if loop_counter % 100 == 0 and len(planes) > 0:
            plane = planes.popitem()[1]
            display_manager.scroll_text("Flight {}\n  Alt: {}".format(plane.flight, plane.alt_geom))

        # run garbage collection
        gc.collect()

    display_manager.refresh_display()
    # print available memory
    print("Loop {} available memory: {} bytes".format(loop_counter, gc.mem_free()))

    # increment loop and sleep for 10 seconds
    loop_counter+=1
    time.sleep(10)
