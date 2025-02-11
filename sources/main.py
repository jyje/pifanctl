import glob, time, typer
import RPi.GPIO as GPIO

app = typer.Typer(
    name = "pifanctl",
    help = "🥧 A CLI for PWM Fan Controlling of Raspberry Pi"
)

def get_max_temperature():
    file_list = glob.glob('/sys/class/thermal/thermal_zone*/temp')
    temp_array = []
    for file_path in file_list:
        with open(file_path, 'r') as file:
            temp_raw = file.read().strip()
            temp = float(temp_raw)/1000
            temp_array.append(temp)
    return max(temp_array)

@app.command()
def check(name: str):
    current_temperature = get_max_temperature()
    print(f"Hello {name}, current temperature: {current_temperature:.3f} °C")

if __name__ == "__main__":
    app()
