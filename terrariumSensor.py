# -*- coding: utf-8 -*-
import terrariumLogging
logger = terrariumLogging.logging.getLogger(__name__)

import datetime
import time
import ow
import os.path
import Adafruit_DHT as dht
import glob
import re
import RPi.GPIO as GPIO
import thread

from hashlib import md5
from gpiozero import MCP3008

from terrariumUtils import terrariumUtils
from terrariumI2CSensor import terrariumSHT2XSensor, terrariumHTU21DSensor, terrariumSi7021Sensor, terrariumBME280Sensor

from gevent import monkey, sleep
monkey.patch_all()

class terrariumSensorYTXXDigital():

  hardwaretype = 'ytxx-digital'

  def __init__(self,gpionummer,gpiopower = None):
    self.__gpionummer = gpionummer
    self.__gpio_power = gpiopower
    self.__alarm = None

    logger.debug('Initializing sensor type \'%s\' with GPIO address %s' % (self.__class__.__name__,self.__gpionummer))
    GPIO.setup(terrariumUtils.to_BCM_port_number(self.__gpionummer), GPIO.IN,pull_up_down=GPIO.PUD_UP)

    if self.__gpio_power is not None:
      # Some kind of 'power management' :) https://raspberrypi.stackexchange.com/questions/68123/preventing-corrosion-on-yl-69
      logger.debug('Enabling power control management on sensor type \'%s\' with GPIO power address %s' % (self.__class__.__name__,self.__gpio_power))
      GPIO.setup(terrariumUtils.to_BCM_port_number(self.__gpio_power), GPIO.OUT)



    #GPIO.add_event_detect(terrariumUtils.to_BCM_port_number(self.__gpionummer), GPIO.BOTH, bouncetime=300)
    #GPIO.add_event_callback(terrariumUtils.to_BCM_port_number(self.__gpionummer), self.__state_change)



  def __get_raw_data(self):
    if self.__gpio_power is not None:
      logger.debug('Powering up sensor type \'%s\' with GPIO address %s' % (self.__class__.__name__,self.__gpionummer))
      GPIO.output(terrariumUtils.to_BCM_port_number(self.__gpio_power),1)
      # Time to get power flowing
      time.sleep(0.5)

    self.__alarm = True if not GPIO.input(terrariumUtils.to_BCM_port_number(self.__gpionummer)) else False
    logger.debug('Read state sensor type \'%s\' with GPIO address %s with current alarm: %s' % (self.__class__.__name__,self.__gpionummer,self.__alarm))

    if self.__gpio_power is not None:
      logger.debug('Powering down sensor type \'%s\' with GPIO address %s' % (self.__class__.__name__,self.__gpionummer))
      GPIO.output(terrariumUtils.to_BCM_port_number(self.__gpio_power),0)

  def __enter__(self):
    """used to enable python's with statement support"""
    return self

  def __exit__(self, type, value, traceback):
    """with support"""
    self.close()

  def close(self):
    logger.debug('Close sensor type \'%s\' with address %s' % (self.__class__.__name__,self.__gpionummer))
    GPIO.cleanup(terrariumUtils.to_BCM_port_number(self.__gpionummer))
    if self.__gpio_power is not None:
      logger.debug('Close power control pin of sensor type \'%s\' with address %s' % (self.__class__.__name__,self.__gpio_power))
      GPIO.cleanup(terrariumUtils.to_BCM_port_number(self.__gpio_power))

  def get_alarm(self):
    self.__get_raw_data()
    return self.__alarm is True

  def get_state(self):
    return (_('Dry') if self.get_alarm() else _('Wet'))

  def get_current(self):
    return 1 if self.get_alarm() else 0

class terrariumSensor:
  UPDATE_TIMEOUT = 30
  VALID_SENSOR_TYPES   = ['temperature','humidity','moisture','distance','ph']
  VALID_DHT_SENSORS    = { 'dht11' : dht.DHT11,
                           'dht22' : dht.DHT22,
                           'am2302': dht.AM2302 }
  VALID_HARDWARE_TYPES = ['owfs','w1','remote','hc-sr04','sku-sen0161'] + VALID_DHT_SENSORS.keys()

  # Append I2C sensors to the list of valid sensors
  VALID_HARDWARE_TYPES.append(terrariumSHT2XSensor.hardwaretype)
  VALID_HARDWARE_TYPES.append(terrariumHTU21DSensor.hardwaretype)
  VALID_HARDWARE_TYPES.append(terrariumSi7021Sensor.hardwaretype)
  VALID_HARDWARE_TYPES.append(terrariumBME280Sensor.hardwaretype)

  # Append moisture sensor(s) to the list of valid sensors
  VALID_HARDWARE_TYPES.append(terrariumSensorYTXXDigital.hardwaretype)

  W1_BASE_PATH = '/sys/bus/w1/devices/'
  W1_TEMP_REGEX = re.compile(r'(?P<type>t|f)=(?P<value>[0-9\-]+)',re.IGNORECASE)

  def __init__(self, id, hardware_type, sensor_type, sensor, name = '', callback_indicator = None):
    self.id = id
    self.set_hardware_type(hardware_type)
    self.set_address(sensor)

    if 'owfs' == self.get_hardware_type():
      # OW Sensor object
      self.sensor = sensor
      self.sensor.useCache(True)
      self.sensor_address = self.sensor.address
    elif 'w1' == self.get_hardware_type():
      # Dirty hack to replace OWFS sensor object for W1 path
      self.sensor_address = sensor
    elif self.get_hardware_type() in terrariumSensor.VALID_DHT_SENSORS.keys():
      # Adafruit_DHT
      self.sensor = dht
      # Dirty hack to set sensor address
      #self.set_address(sensor)

    self.set_name(name)
    self.set_type(sensor_type,callback_indicator)
    self.set_alarm_min(0)
    self.set_alarm_max(0)
    self.set_limit_min(0)
    self.set_limit_max(100)
    if 'hc-sr04' == self.get_hardware_type():
      # Limit 10 meters
      self.set_limit_max(100000)

    if self.id is None:
      self.id = md5(b'' + self.get_address().replace('-','').upper() + self.get_type()).hexdigest()

    self.current = float(0)
    self.last_update = datetime.datetime.fromtimestamp(0)
    logger.info('Loaded %s %s sensor \'%s\' on location %s.' % (self.get_hardware_type(),self.get_type(),self.get_name(),self.get_address()))
    self.update()

  @staticmethod
  def scan(port,unit_indicator): # TODO: Wants a callback per sensor here....?
    starttime = time.time()
    logger.debug('Start scanning for temperature/humidity sensors')
    sensor_list = []

    if port > 0:
      try:
        ow.init(str(port));
        sensorsList = ow.Sensor('/').sensorList()
        for sensor in sensorsList:
          if 'temperature' in sensor.entryList():
            sensor_list.append(terrariumSensor(None,
                                               'owfs',
                                               'temperature',
                                               sensor,
                                               callback_indicator=unit_indicator))

          if 'humidity' in sensor.entryList():
            sensor_list.append(terrariumSensor(None,
                                               'owfs',
                                               'humidity',
                                               sensor,
                                               callback_indicator=unit_indicator))

      except ow.exNoController:
        logger.debug('OWFS file system is not actve / installed on this device!')
        pass

    # Scanning w1 system bus
    for address in glob.iglob(terrariumSensor.W1_BASE_PATH + '[1-9][0-9]-*'):
      if not os.path.isfile(address + '/w1_slave'):
        break

      data = ''
      with open(address + '/w1_slave', 'r') as w1data:
        data = w1data.read()

      w1data = terrariumSensor.W1_TEMP_REGEX.search(data)
      if w1data:
        # Found valid data
        sensor_list.append(terrariumSensor(None,
                                           'w1',
                                           ('temperature' if 't' == w1data.group('type') else 'humidity'),
                                           address.replace(terrariumSensor.W1_BASE_PATH,''),
                                           callback_indicator=unit_indicator))

    logger.info('Found %d temperature/humidity sensors in %.5f seconds' % (len(sensor_list),time.time() - starttime))
    return sensor_list

  def update(self, force = False):
    now = datetime.datetime.now()
    if now - self.last_update > datetime.timedelta(seconds=terrariumSensor.UPDATE_TIMEOUT) or force:
      logger.debug('Updating %s %s sensor \'%s\'' % (self.get_hardware_type(),self.get_type(), self.get_name()))
      old_current = self.get_current()
      current = None
      try:
        starttime = time.time()
        if 'remote' == self.get_hardware_type():
          url_data = terrariumUtils.parse_url(self.get_address())
          if url_data is False:
            logger.error('Remote url \'%s\' for sensor \'%s\' is not a valid remote source url!' % (self.get_address(),self.get_name()))
          else:
            data = terrariumUtils.get_remote_data(self.get_address())
            if data is not None:
              current = float(data)
            else:
              logger.warning('Remote sensor \'%s\' got error from remote source \'%s\'' % (self.get_name(),self.get_address()))

        elif 'hc-sr04' == self.get_hardware_type():
          GPIO.output(terrariumUtils.to_BCM_port_number(self.sensor_address['TRIG']), False)
          time.sleep(2)
          GPIO.output(terrariumUtils.to_BCM_port_number(self.sensor_address['TRIG']), True)
          time.sleep(0.00001)
          GPIO.output(terrariumUtils.to_BCM_port_number(self.sensor_address['TRIG']), False)
          pulse_start = time.time()
          while GPIO.input(terrariumUtils.to_BCM_port_number(self.sensor_address['ECHO']))==0:
            pulse_start = time.time()
          pulse_end = time.time()
          while GPIO.input(terrariumUtils.to_BCM_port_number(self.sensor_address['ECHO']))==1:
            pulse_end = time.time()

          pulse_duration = pulse_end - pulse_start
          # https://www.modmypi.com/blog/hc-sr04-ultrasonic-range-sensor-on-the-raspberry-pi
          # Measure in centimetre
          current = round(pulse_duration * 17150,2)

        elif 'sku-sen0161' == self.get_hardware_type():
          # Do multiple measurements...
          values = []
          for counter in range(5):
            analog_port = MCP3008(channel=int(self.get_address()))
            # https://github.com/theyosh/TerrariumPI/issues/108
            # We measure the values in volts already, so no deviding by 1000 as original script does
            values.append((analog_port.value * ( 5000.0 / 1024.0)) * 3.3 + 0.1614)
            time.sleep(0.2)

          # sort values from low to high
          values.sort()
          # Calculate average. Exclude the min and max value. And therefore devide by 3
          current = round((sum(values[1:-1]) / 3.0),2)

        elif 'temperature' == self.get_type():
          if self.get_hardware_type() == 'owfs':
            current = float(self.sensor.temperature)

          elif self.get_hardware_type() in [terrariumSHT2XSensor.hardwaretype,
                                            terrariumHTU21DSensor.hardwaretype,
                                            terrariumSi7021Sensor.hardwaretype,
                                            terrariumBME280Sensor.hardwaretype]:
            # This will open a new connection to the sensor
            if terrariumSHT2XSensor.hardwaretype == self.get_hardware_type():
              hardwaresensor = terrariumSHT2XSensor(int(self.sensor_address['device']),int('0x' + self.sensor_address['address'],16))
            elif terrariumHTU21DSensor.hardwaretype == self.get_hardware_type():
              hardwaresensor = terrariumHTU21DSensor(int(self.sensor_address['device']),int('0x' + self.sensor_address['address'],16))
            elif terrariumSi7021Sensor.hardwaretype == self.get_hardware_type():
              hardwaresensor = terrariumSi7021Sensor(int(self.sensor_address['device']),int('0x' + self.sensor_address['address'],16))
            elif terrariumBME280Sensor.hardwaretype == self.get_hardware_type():
              hardwaresensor = terrariumBME280Sensor(int(self.sensor_address['device']),int('0x' + self.sensor_address['address'],16))

            with hardwaresensor as sensor:
              current = sensor.read_temperature()
              if terrariumUtils.is_float(current):
                current = float(current)

              # This will 'automatically' close the connection to the sensor

          elif self.get_hardware_type() == 'w1':
            data = ''
            if os.path.isfile(terrariumSensor.W1_BASE_PATH + self.get_address() + '/w1_slave'):
              with open(terrariumSensor.W1_BASE_PATH + self.get_address() + '/w1_slave', 'r') as w1data:
                data = w1data.read()

              w1data = terrariumSensor.W1_TEMP_REGEX.search(data)
              if w1data:
                # Found data
                current = float(w1data.group('value')) / 1000
              else:
                logger.error('Error reading 1Wire temperature %s at location %s. Current data: %s', (self.get_name(),self.get_address(),data))
            else:
              logger.error('1 Wire sensor %s at location %s is not available!!!', (self.get_name(),self.get_address()))
          elif self.get_hardware_type() in terrariumSensor.VALID_DHT_SENSORS.keys():
            time.sleep(2.1)
            humidity, temperature = self.sensor.read_retry(terrariumSensor.VALID_DHT_SENSORS[self.get_hardware_type()],
                                                           float(terrariumUtils.to_BCM_port_number(self.sensor_address)),
                                                           5)
            if temperature is not None:
              current = float(temperature)

        elif 'humidity' == self.get_type():
          if self.get_hardware_type() == 'owfs':
            current = float(self.sensor.humidity)

          elif self.get_hardware_type() in [terrariumSHT2XSensor.hardwaretype,
                                            terrariumHTU21DSensor.hardwaretype,
                                            terrariumSi7021Sensor.hardwaretype,
                                            terrariumBME280Sensor.hardwaretype]:
            # This will open a new connection to the sensor
            if terrariumSHT2XSensor.hardwaretype == self.get_hardware_type():
              hardwaresensor = terrariumSHT2XSensor(int(self.sensor_address['device']),int('0x' + self.sensor_address['address'],16))
            elif terrariumHTU21DSensor.hardwaretype == self.get_hardware_type():
              hardwaresensor = terrariumHTU21DSensor(int(self.sensor_address['device']),int('0x' + self.sensor_address['address'],16))
            elif terrariumSi7021Sensor.hardwaretype == self.get_hardware_type():
              hardwaresensor = terrariumSi7021Sensor(int(self.sensor_address['device']),int('0x' + self.sensor_address['address'],16))
            elif terrariumBME280Sensor.hardwaretype == self.get_hardware_type():
              hardwaresensor = terrariumBME280Sensor(int(self.sensor_address['device']),int('0x' + self.sensor_address['address'],16))

            with hardwaresensor as sensor:
              current = sensor.read_humidity()
              if terrariumUtils.is_float(current):
                current = float(current)

              # This will 'automatically' close the connection to the sensor

          elif self.get_hardware_type() == 'w1':
            # Not tested / No hardware to test with
            pass

          elif self.get_hardware_type() in terrariumSensor.VALID_DHT_SENSORS.keys():
            time.sleep(2.1)
            humidity, temperature = self.sensor.read_retry(terrariumSensor.VALID_DHT_SENSORS[self.get_hardware_type()],
                                                           float(terrariumUtils.to_BCM_port_number(self.sensor_address)),
                                                           5)
            if humidity is not None:
              current = float(humidity)


        elif 'moisture' == self.get_type():
          if terrariumSensorYTXXDigital.hardwaretype == self.get_hardware_type():
            address = [self.sensor_address,None]
            if ',' in address:
              address = self.sensor_address.split(',')

            hardwaresensor = terrariumSensorYTXXDigital(address[0],address[1])

          with hardwaresensor as sensor:
            current = sensor.get_current()
            if terrariumUtils.is_float(current):
              current = float(current)

        if current is None or not (self.get_limit_min() <= current <= self.get_limit_max()):
          # Invalid current value.... log and ingore
          logger.warn('Measured value %s%s from %s sensor \'%s\' is outside valid range %.2f%s - %.2f%s in %.5f seconds.' % (current,
                                                                                                                             self.get_indicator(),
                                                                                                                             self.get_type(),
                                                                                                                             self.get_name(),
                                                                                                                             self.get_limit_min(),
                                                                                                                             self.get_indicator(),
                                                                                                                             self.get_limit_max(),
                                                                                                                             self.get_indicator(),
                                                                                                                             time.time()-starttime))

        else:
          self.current = current
          self.last_update = now
          logger.info('Updated %s sensor \'%s\' from %.2f%s to %.2f%s in %.5f seconds' % (self.get_type(),
                                                                                          self.get_name(),
                                                                                          old_current,
                                                                                          self.get_indicator(),
                                                                                          self.get_current(),
                                                                                          self.get_indicator(),
                                                                                          time.time()-starttime))
      except Exception, ex:
        print ex
        logger.exception('Error updating %s %s sensor \'%s\' with error:' % (self.get_hardware_type(),
                                                                              self.get_type(),
                                                                              self.get_name()))
        logger.exception(ex)

  def get_data(self):
    data = {'id' : self.get_id(),
            'hardwaretype' : self.get_hardware_type(),
            'address' : self.get_address(),
            'type' : self.get_type(),
            'indicator' : self.get_indicator(),
            'name' : self.get_name(),
            'current' : self.get_current(),
            'alarm_min' : self.get_alarm_min(),
            'alarm_max' : self.get_alarm_max(),
            'limit_min' : self.get_limit_min(),
            'limit_max' : self.get_limit_max(),
            'alarm' : self.get_alarm()
            }

    return data

  def get_id(self):
    return self.id

  def get_hardware_type(self):
    return self.hardwaretype

  def set_hardware_type(self,type):
    if type in terrariumSensor.VALID_HARDWARE_TYPES:
      self.hardwaretype = type

  def set_type(self,type,indicator):
    if type in terrariumSensor.VALID_SENSOR_TYPES:
      self.type = type
      self.__indicator = indicator

  def get_type(self):
    return self.type

  def get_indicator(self):
    # Use a callback from terrariumEngine for 'realtime' updates
    return self.__indicator(self.get_type())

  def get_address(self):
    address = self.sensor_address
    if 'hc-sr04' == self.get_hardware_type():
      address = str(self.sensor_address['TRIG']) + ',' + str(self.sensor_address['ECHO'])
    elif self.get_hardware_type() in [terrariumSHT2XSensor.hardwaretype,
                                      terrariumHTU21DSensor.hardwaretype,
                                      terrariumSi7021Sensor.hardwaretype,
                                      terrariumBME280Sensor.hardwaretype]:
      address = str(self.sensor_address['device']) + ',' + str(self.sensor_address['address'])

    return address

  def set_address(self,address):
    # Can't set OWFS or W1 sensor addresses. This is done by the OWFS software or kernel OS
    if self.get_hardware_type() not in ['owfs','w1']:
      self.sensor_address = address

      if 'hc-sr04' == self.get_hardware_type() and ',' in address:
        sensor = address.split(',')
        self.sensor_address = {'TRIG' : sensor[0] , 'ECHO' : sensor[1]}
        try:
          GPIO.setup(terrariumUtils.to_BCM_port_number(self.sensor_address['TRIG']),GPIO.OUT)
          GPIO.setup(terrariumUtils.to_BCM_port_number(self.sensor_address['ECHO']),GPIO.IN)

        except Exception, err:
          logger.warning(err)
          pass
      elif self.get_hardware_type() in [terrariumSHT2XSensor.hardwaretype,
                                      terrariumHTU21DSensor.hardwaretype,
                                      terrariumSi7021Sensor.hardwaretype,
                                      terrariumBME280Sensor.hardwaretype]:
        sensor = address.split(',')
        if len(sensor) == 2:
          self.sensor_address = {'device' : sensor[0] , 'address' : sensor[1]}
        else:
          self.sensor_address = {'device' : 1 , 'address' : address}

  def set_name(self,name):
    self.name = str(name)

  def get_name(self):
    return self.name

  def get_alarm_min(self):
    return self.alarm_min

  def set_alarm_min(self,limit):
    if terrariumSensorYTXXDigital.hardwaretype == self.get_hardware_type():
      # Hard limit for better gauge graphs. Sensor can only return 0 or 1
      limit = -1.05

    self.alarm_min = float(limit)

  def get_alarm_max(self):
    return self.alarm_max

  def set_alarm_max(self,limit):
    if terrariumSensorYTXXDigital.hardwaretype == self.get_hardware_type():
      # Hard limit for better gauge graphs. Sensor can only return 0 or 1
      limit = 1.05

    self.alarm_max = float(limit)

  def get_limit_min(self):
    return self.limit_min

  def set_limit_min(self,limit):
    if terrariumSensorYTXXDigital.hardwaretype == self.get_hardware_type():
      # Hard limit for better gauge graphs. Sensor can only return 0 or 1
      limit = -1.1

    self.limit_min = float(limit)

  def get_limit_max(self):
    return self.limit_max

  def set_limit_max(self,limit):
    if terrariumSensorYTXXDigital.hardwaretype == self.get_hardware_type():
      # Hard limit for better gauge graphs. Sensor can only return 0 or 1
      limit = 1.1

    self.limit_max = float(limit)

  def get_current(self, force = False):
    current = self.current
    indicator = self.get_indicator().lower()

    if 'f' == indicator:
      current = terrariumUtils.to_fahrenheit(self.current)
    elif 'inch' == indicator:
      current = terrariumUtils.to_inches(self.current)

    return float(current)

  def get_alarm(self):
    return not self.get_alarm_min() < self.get_current() < self.get_alarm_max()

  def stop(self):
    if 'hc-sr04' == self.get_hardware_type():
      GPIO.cleanup(terrariumUtils.to_BCM_port_number(self.sensor_address['TRIG']))
      GPIO.cleanup(terrariumUtils.to_BCM_port_number(self.sensor_address['ECHO']))
    elif self.get_hardware_type() in terrariumSensor.VALID_DHT_SENSORS.keys():
      GPIO.cleanup(terrariumUtils.to_BCM_port_number(self.sensor_address))

    logger.info('Cleaning up sensor %s at location %s' % (self.get_name(), self.get_address()))
