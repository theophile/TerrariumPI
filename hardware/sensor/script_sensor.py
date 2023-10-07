from . import terrariumSensor, terrariumSensorLoadingException
from terrariumUtils import terrariumUtils

from pathlib import Path

class terrariumScriptSensor(terrariumSensor):
  HARDWARE = 'script'
  # Empty TYPES list as this will be filled with all available hardware TYPES
  TYPES    = []
  NAME     = 'Script sensor'

  def _load_hardware(self):
    self.address_parsed = [part.strip() for part in self.address.split(',') if '' != part.strip()]
    script = Path(self.address_parsed[0])
    if not script.exists():
      raise terrariumSensorLoadingException(f'Invalid script location for sensor {self}: {script}')

    if oct(script.stat().st_mode)[-3:] not in ['777','775','755']:
      raise terrariumSensorLoadingException(f'Script {script} for sensor {self} is not executable.')

    return self.address_parsed

  def _get_data(self):
    data = {}
    try:
      data[self.sensor_type] = float(terrariumUtils.get_script_data(self.address).decode('utf-8').strip())
    except Exception:
      return None

    return data
