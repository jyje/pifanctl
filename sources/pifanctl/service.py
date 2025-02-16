import time, glob, logging

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

    assert len(temp_array) > 0, "No temperature data available"

    return temp_array


def set_pwm_fan(
    pin: int,
    pwm_frequency: int,
    duty_cycle_initial: float,
):
    set_warnings = False
    set_mode = GPIO.BCM
    setup_direction = GPIO.OUT

    GPIO.setwarnings(set_warnings)
    GPIO.cleanup()
    GPIO.setmode(set_mode)
    GPIO.setup(pin, setup_direction)

    pwm = GPIO.PWM(pin, pwm_frequency)
    pwm.start(duty_cycle_initial)

    return pwm


def run_pwm_fan(
    fan: GPIO.PWM,
    target_temperature: float,
    pwm_refresh_interval: float,
    duty_cycle_initial: float,
    duty_cycle_step: float,
):
    duty_cycle = duty_cycle_initial

    while True:
        current_temperature = max(get_temperature())

        if current_temperature > target_temperature:
            duty_cycle = min(100, duty_cycle + duty_cycle_step)
        else:
            duty_cycle = max(0, duty_cycle - duty_cycle_step)

        fan.ChangeDutyCycle(duty_cycle)

        logger.info(f"Duty: {duty_cycle:.1f}%, Temperature: {current_temperature:.1f}°C")

        time.sleep(pwm_refresh_interval)
