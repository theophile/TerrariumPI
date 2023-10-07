from . import terrariumRelay, terrariumRelayDimmer, terrariumRelayLoadingException
from terrariumUtils import terrariumUtils

from pathlib import Path
import subprocess


class relayScriptMixin():
  def _load_hardware(self):
    self.address_parsed = [part.strip() for part in self.address.split(',') if '' != part.strip()]
    script = Path(self.address_parsed[0])
    if not script.exists():
      raise terrariumRelayLoadingException(f'Invalid script location for relay {self}: {script}')

    if oct(script.stat().st_mode)[-3:] not in ['777','775','755','744','544','554','555','550','540','770','750','740']:
      raise terrariumRelayLoadingException(f'Script {script} for relay {self} is not executable.')

    return self.address_parsed

  def _set_hardware_value(self, state):
    address = ' '.join(self.address_parsed)
    cmd = f'{address} --value={state}'

    try:
      terrariumUtils.get_script_data(cmd)
    except subprocess.CalledProcessError:
      # Device does not exists....
      return None

    return True

  def _get_hardware_value(self):

    try:
      data = float(terrariumUtils.get_script_data(self.address_parsed[0]).decode('utf-8').strip())

      # When the return value is -1, it means that there is not readout possible. So return the current state from memory
      if -1.0 == data:
        data = self.state
    except subprocess.CalledProcessError:
      # Device does not exists....
      return None

    return data


class terrariumRelayScript(relayScriptMixin, terrariumRelay):
  HARDWARE = 'script'
  NAME = 'Script relay'

  def _get_hardware_value(self):
    data = super()._get_hardware_value()
    return self.ON if data != 0.0 else self.OFF


class terrariumDimmerScript(relayScriptMixin, terrariumRelayDimmer):
  HARDWARE = 'script-dimmer'
  NAME = 'Script dimmer'
