import glob, logging

logger = logging.getLogger(__name__)

try:
    import RPi.GPIO as GPIO
    RPI_DEVICE = True
except Exception as e:
    logger.info(f"Impossible to import RPi.GPIO: {e}")
    
    logger.info("Mock.GPIO will be used")
    import Mock.GPIO as GPIO
    RPI_DEVICE = False


def get_temperature():
    if not RPI_DEVICE:
        import random
        mean = -50
        std = 10

        value = random.gauss(mean, std)
        return [ value ]

    file_list = glob.glob('/sys/class/thermal/thermal_zone*/temp')
    temp_array = []
    for file_path in file_list:
        with open(file_path, 'r') as file:
            temp_raw = file.read().strip()
            temp = float(temp_raw)/1000
            temp_array.append(temp)
            logger.debug(f"Temperature reading from {file_path}: {temp}°C")

    return temp_array
