import glob, logging

try:
    import RPi.GPIO as GPIO
    RPI_DEVICE = True
except ImportError as e:
    import Mock.GPIO as GPIO
    RPI_DEVICE = False


def get_temperature():
    if not RPI_DEVICE:
        import random
        mean = 50
        std = 10
        return [ random.gauss(mean, std) ]

    file_list = glob.glob('/sys/class/thermal/thermal_zone*/temp')
    temp_array = []
    for file_path in file_list:
        with open(file_path, 'r') as file:
            temp_raw = file.read().strip()
            temp = float(temp_raw)/1000
            temp_array.append(temp)

    return temp_array
