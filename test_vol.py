from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

devices = AudioUtilities.GetSpeakers()
interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
vol = cast(interface, POINTER(IAudioEndpointVolume))
print("Current volume:", vol.GetMasterVolumeLevelScalar())
vol.SetMasterVolumeLevelScalar(0.5, None)
print("Set to 50% - did system volume change?")