import os
import io
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime, timedelta

import requests

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

import os

API_KEY = os.environ.get("OPENWEATHER_API_KEY", "")

CURRENT_WEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"
ICON_URL_TEMPLATE = "https://openweathermap.org/img/wn/{icon}@2x.png"
IPINFO_URL = "https://ipinfo.io/json"
REQUEST_TIMEOUT = 10  # seconds

def fetch_current_weather(location, api_key):
    """Return (data_dict, error_message). Exactly one will be None."""
    params = {"q": location, "appid": api_key, "units": "metric"}
    try:
        resp = requests.get(CURRENT_WEATHER_URL, params=params, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.Timeout:
        return None, "Request timed out. Check your internet connection."
    except requests.exceptions.ConnectionError:
        return None, "Network error - could not reach the weather server."
    except requests.exceptions.RequestException as e:
        return None, f"Unexpected network error: {e}"

    if resp.status_code == 401:
        return None, "Invalid API key. Check your OPENWEATHER_API_KEY."
    if resp.status_code == 404:
        return None, f"City '{location}' not found. Check the spelling."
    if resp.status_code != 200:
        return None, f"Unexpected server response (status {resp.status_code})."

    try:
        return resp.json(), None
    except ValueError:
        return None, "Could not parse the server's response."


def fetch_forecast(location, api_key):
    """Return (data_dict, error_message) for the 5-day/3-hour forecast."""
    params = {"q": location, "appid": api_key, "units": "metric"}
    try:
        resp = requests.get(FORECAST_URL, params=params, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.Timeout:
        return None, "Forecast request timed out."
    except requests.exceptions.ConnectionError:
        return None, "Network error while fetching forecast."
    except requests.exceptions.RequestException as e:
        return None, f"Unexpected network error: {e}"

    if resp.status_code == 401:
        return None, "Invalid API key."
    if resp.status_code == 404:
        return None, f"City '{location}' not found for forecast."
    if resp.status_code != 200:
        return None, f"Unexpected server response (status {resp.status_code})."

    try:
        return resp.json(), None
    except ValueError:
        return None, "Could not parse the forecast response."


def fetch_icon_bytes(icon_code):
    """Download a weather icon's raw bytes. Returns None on failure."""
    try:
        url = ICON_URL_TEMPLATE.format(icon=icon_code)
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            return resp.content
    except requests.exceptions.RequestException:
        pass
    return None


def detect_location_by_ip():
    """
    Bonus feature: auto-detect the user's city using ipinfo.io.
    Returns a city name string, or None if detection fails.
    """
    try:
        resp = requests.get(IPINFO_URL, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            city = data.get("city")
            return city
    except requests.exceptions.RequestException:
        pass
    return None


def build_hourly_forecast(forecast_data, count=2):
    """
    OpenWeatherMap's free forecast API returns data in 3-hour steps.
    To approximate "next 6 hours", we take the next 2 entries (2 x 3h = 6h).
    Returns a list of dicts: {time, temp_c, icon, description}
    """
    entries = forecast_data.get("list", [])[:count]
    hourly = []
    for entry in entries:
        dt_txt = entry.get("dt_txt")
        try:
            dt_obj = datetime.strptime(dt_txt, "%Y-%m-%d %H:%M:%S")
            time_label = dt_obj.strftime("%I:%M %p")
        except (ValueError, TypeError):
            time_label = dt_txt or "N/A"

        weather_list = entry.get("weather", [])
        icon = weather_list[0]["icon"] if weather_list else "01d"
        description = weather_list[0]["description"].title() if weather_list else "N/A"
        temp_c = entry.get("main", {}).get("temp")

        hourly.append({
            "time": time_label,
            "temp_c": temp_c,
            "icon": icon,
            "description": description,
        })
    return hourly


def build_daily_forecast(forecast_data, days=5):
    """
    Aggregate the 3-hour forecast list into one entry per day (using the
    reading closest to midday as representative), for up to `days` days.
    Returns a list of dicts: {date, temp_c, icon, description}
    """
    entries = forecast_data.get("list", [])
    by_date = {}

    for entry in entries:
        dt_txt = entry.get("dt_txt", "")
        date_part, _, time_part = dt_txt.partition(" ")
        if not date_part:
            continue
        if date_part not in by_date or _closer_to_noon(time_part, by_date[date_part][1]):
            by_date[date_part] = (entry, time_part)

    daily = []
    for date_str in sorted(by_date.keys())[:days]:
        entry, _ = by_date[date_str]
        weather_list = entry.get("weather", [])
        icon = weather_list[0]["icon"] if weather_list else "01d"
        description = weather_list[0]["description"].title() if weather_list else "N/A"
        temp_c = entry.get("main", {}).get("temp")

        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
            date_label = date_obj.strftime("%a, %b %d")
        except ValueError:
            date_label = date_str

        daily.append({
            "date": date_label,
            "temp_c": temp_c,
            "icon": icon,
            "description": description,
        })
    return daily


def _closer_to_noon(time_a, time_b):
    """Helper: is time_a closer to 12:00:00 than time_b?"""
    def to_minutes(t):
        try:
            h, m, _ = t.split(":")
            return int(h) * 60 + int(m)
        except (ValueError, AttributeError):
            return 0

    return abs(to_minutes(time_a) - 720) < abs(to_minutes(time_b) - 720)


def c_to_f(celsius):
    if celsius is None:
        return None
    return (celsius * 9 / 5) + 32

class WeatherApp(tk.Tk):
    BG_COLOR = "#eaf2fb"
    ACCENT_COLOR = "#1f6feb"
    CARD_COLOR = "#ffffff"
    TEXT_COLOR = "#1a1a1a"
    MUTED_COLOR = "#5a6472"

    def __init__(self):
        super().__init__()
        self.title("Weather App")
        self.geometry("880x640")
        self.minsize(820, 600)
        self.configure(bg=self.BG_COLOR)

        self.unit = tk.StringVar(value="C")  # "C" or "F"
        self.icon_cache = {}          # icon_code -> ImageTk.PhotoImage
        self._last_current_data = None
        self._last_forecast_data = None

        self._build_style()
        self._build_layout()

        if not API_KEY:
            self._show_error(
                "No API key found. Set the OPENWEATHER_API_KEY environment "
                "variable, then restart the app.\nGet a free key at "
                "openweathermap.org/api"
            )
        else:
            self._auto_detect_location()


    def _build_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("TFrame", background=self.BG_COLOR)
        style.configure("Card.TFrame", background=self.CARD_COLOR)
        style.configure(
            "TButton",
            font=("Segoe UI", 10, "bold"),
            padding=8,
        )
        style.configure(
            "Accent.TButton",
            background=self.ACCENT_COLOR,
            foreground="white",
        )
        style.map("Accent.TButton", background=[("active", "#155ec4")])

    def _build_layout(self):
        top_frame = ttk.Frame(self, padding=(16, 16, 16, 8))
        top_frame.pack(fill="x")

        ttk.Label(
            top_frame, text="🌦  Weather App", font=("Segoe UI", 18, "bold"),
            background=self.BG_COLOR,
        ).pack(side="left")

        search_frame = ttk.Frame(top_frame)
        search_frame.pack(side="right")

        self.city_entry = ttk.Entry(search_frame, width=28, font=("Segoe UI", 11))
        self.city_entry.pack(side="left", padx=(0, 8))
        self.city_entry.bind("<Return>", lambda e: self.on_get_weather())

        self.get_weather_btn = ttk.Button(
            search_frame, text="Get Weather", style="Accent.TButton",
            command=self.on_get_weather,
        )
        self.get_weather_btn.pack(side="left", padx=(0, 8))

        self.unit_toggle_btn = ttk.Button(
            search_frame, text="°C / °F", command=self.on_toggle_unit,
        )
        self.unit_toggle_btn.pack(side="left")

        self.error_var = tk.StringVar(value="")
        self.error_label = tk.Label(
            self, textvariable=self.error_var, bg="#fdecea", fg="#b3261e",
            font=("Segoe UI", 10, "bold"), wraplength=840, justify="left",
            padx=12, pady=8,
        )

        current_card = ttk.Frame(self, style="Card.TFrame", padding=16)
        current_card.pack(fill="x", padx=16, pady=8)

        self.icon_label = tk.Label(current_card, bg=self.CARD_COLOR)
        self.icon_label.pack(side="left", padx=(0, 16))

        info_frame = ttk.Frame(current_card, style="Card.TFrame")
        info_frame.pack(side="left", fill="both", expand=True)

        self.city_label = tk.Label(
            info_frame, text="Enter a city to begin", font=("Segoe UI", 16, "bold"),
            bg=self.CARD_COLOR, fg=self.TEXT_COLOR, anchor="w",
        )
        self.city_label.pack(fill="x")

        self.temp_label = tk.Label(
            info_frame, text="--", font=("Segoe UI", 28, "bold"),
            bg=self.CARD_COLOR, fg=self.ACCENT_COLOR, anchor="w",
        )
        self.temp_label.pack(fill="x")

        self.condition_label = tk.Label(
            info_frame, text="", font=("Segoe UI", 12), bg=self.CARD_COLOR,
            fg=self.MUTED_COLOR, anchor="w",
        )
        self.condition_label.pack(fill="x")

        details_frame = ttk.Frame(info_frame, style="Card.TFrame")
        details_frame.pack(fill="x", pady=(6, 0))

        self.humidity_label = tk.Label(
            details_frame, text="Humidity: --", bg=self.CARD_COLOR,
            fg=self.MUTED_COLOR, font=("Segoe UI", 10),
        )
        self.humidity_label.pack(side="left", padx=(0, 16))

        self.wind_label = tk.Label(
            details_frame, text="Wind: --", bg=self.CARD_COLOR,
            fg=self.MUTED_COLOR, font=("Segoe UI", 10),
        )
        self.wind_label.pack(side="left")

        ttk.Label(
            self, text="Next 6 Hours", font=("Segoe UI", 12, "bold"),
            background=self.BG_COLOR,
        ).pack(anchor="w", padx=20, pady=(8, 2))

        self.hourly_frame = ttk.Frame(self, padding=(4, 4))
        self.hourly_frame.pack(fill="x", padx=16)

        ttk.Label(
            self, text="Next 5 Days", font=("Segoe UI", 12, "bold"),
            background=self.BG_COLOR,
        ).pack(anchor="w", padx=20, pady=(12, 2))

        self.daily_frame = ttk.Frame(self, padding=(4, 4))
        self.daily_frame.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    def _show_error(self, message):
        self.error_var.set(f"⚠️  {message}")
        self.error_label.pack(fill="x", padx=16, pady=(0, 8))

    def _clear_error(self):
        self.error_var.set("")
        self.error_label.pack_forget()

    def on_get_weather(self):
        city = self.city_entry.get().strip()
        if not city:
            self._show_error("Please enter a city name before searching.")
            return

        if not API_KEY:
            self._show_error(
                "No API key configured. Set OPENWEATHER_API_KEY and restart."
            )
            return

        self._clear_error()
        self.get_weather_btn.config(state="disabled", text="Loading...")
        threading.Thread(target=self._fetch_and_render, args=(city,), daemon=True).start()

    def on_toggle_unit(self):
        self.unit.set("F" if self.unit.get() == "C" else "C")

        if self._last_current_data:
            self.after(0, self._render_current, self._last_current_data)
        if self._last_forecast_data:
            self.after(0, self._render_hourly, self._last_forecast_data)
            self.after(0, self._render_daily, self._last_forecast_data)

    def _fetch_and_render(self, city):
        current_data, err1 = fetch_current_weather(city, API_KEY)
        forecast_data, err2 = fetch_forecast(city, API_KEY)

        error_message = err1 or err2
        if error_message:
            self.after(0, self._on_fetch_error, error_message)
            return

        self._last_current_data = current_data
        self._last_forecast_data = forecast_data

        self.after(0, self._render_current, current_data)
        self.after(0, self._render_hourly, forecast_data)
        self.after(0, self._render_daily, forecast_data)
        self.after(0, self._reset_button)

    def _on_fetch_error(self, message):
        self._show_error(message)
        self._reset_button()

    def _reset_button(self):
        self.get_weather_btn.config(state="normal", text="Get Weather")

    def _format_temp(self, temp_c):
        if temp_c is None:
            return "--"
        if self.unit.get() == "C":
            return f"{temp_c:.1f}°C"
        return f"{c_to_f(temp_c):.1f}°F"

    def _get_icon_image(self, icon_code, size=(80, 80)):
        cache_key = (icon_code, size)
        if cache_key in self.icon_cache:
            return self.icon_cache[cache_key]

        if not PIL_AVAILABLE:
            return None

        icon_bytes = fetch_icon_bytes(icon_code)
        if not icon_bytes:
            return None

        try:
            img = Image.open(io.BytesIO(icon_bytes)).resize(size)
            photo = ImageTk.PhotoImage(img)
            self.icon_cache[cache_key] = photo
            return photo
        except Exception:
            return None

    def _render_current(self, data):
        city_name = data.get("name", "Unknown")
        country = data.get("sys", {}).get("country", "")
        main = data.get("main", {})
        temp_c = main.get("temp")
        humidity = main.get("humidity")
        weather_list = data.get("weather", [])
        description = weather_list[0]["description"].title() if weather_list else "N/A"
        icon_code = weather_list[0]["icon"] if weather_list else "01d"
        wind_speed = data.get("wind", {}).get("speed")

        self.city_label.config(text=f"{city_name}{', ' + country if country else ''}")
        self.temp_label.config(text=self._format_temp(temp_c))
        self.condition_label.config(text=description)
        self.humidity_label.config(text=f"Humidity: {humidity}%" if humidity is not None else "Humidity: --")
        self.wind_label.config(text=f"Wind: {wind_speed} m/s" if wind_speed is not None else "Wind: --")

        photo = self._get_icon_image(icon_code, size=(90, 90))
        if photo:
            self.icon_label.config(image=photo, text="")
            self.icon_label.image = photo  # keep a reference
        else:
            self.icon_label.config(image="", text="🌤")

    def _render_hourly(self, forecast_data):
        for widget in self.hourly_frame.winfo_children():
            widget.destroy()

        hourly = build_hourly_forecast(forecast_data, count=2)  # 2 x 3h = 6h
        if not hourly:
            ttk.Label(self.hourly_frame, text="No hourly data available.").pack(side="left")
            return

        for item in hourly:
            card = tk.Frame(self.hourly_frame, bg=self.CARD_COLOR, padx=12, pady=10)
            card.pack(side="left", padx=6, fill="x", expand=True)

            tk.Label(card, text=item["time"], bg=self.CARD_COLOR,
                     font=("Segoe UI", 10, "bold")).pack()

            photo = self._get_icon_image(item["icon"], size=(48, 48))
            icon_lbl = tk.Label(card, bg=self.CARD_COLOR)
            if photo:
                icon_lbl.config(image=photo)
                icon_lbl.image = photo
            else:
                icon_lbl.config(text="🌤", font=("Segoe UI", 20))
            icon_lbl.pack()

            tk.Label(card, text=self._format_temp(item["temp_c"]), bg=self.CARD_COLOR,
                     font=("Segoe UI", 11)).pack()
            tk.Label(card, text=item["description"], bg=self.CARD_COLOR,
                     fg=self.MUTED_COLOR, font=("Segoe UI", 8), wraplength=100,
                     justify="center").pack()

    def _render_daily(self, forecast_data):
        for widget in self.daily_frame.winfo_children():
            widget.destroy()

        daily = build_daily_forecast(forecast_data, days=5)
        if not daily:
            ttk.Label(self.daily_frame, text="No daily data available.").pack(side="left")
            return

        for item in daily:
            card = tk.Frame(self.daily_frame, bg=self.CARD_COLOR, padx=12, pady=10)
            card.pack(side="left", padx=6, fill="both", expand=True)

            tk.Label(card, text=item["date"], bg=self.CARD_COLOR,
                     font=("Segoe UI", 10, "bold")).pack()

            photo = self._get_icon_image(item["icon"], size=(48, 48))
            icon_lbl = tk.Label(card, bg=self.CARD_COLOR)
            if photo:
                icon_lbl.config(image=photo)
                icon_lbl.image = photo
            else:
                icon_lbl.config(text="🌤", font=("Segoe UI", 20))
            icon_lbl.pack()

            tk.Label(card, text=self._format_temp(item["temp_c"]), bg=self.CARD_COLOR,
                     font=("Segoe UI", 11)).pack()
            tk.Label(card, text=item["description"], bg=self.CARD_COLOR,
                     fg=self.MUTED_COLOR, font=("Segoe UI", 8), wraplength=100,
                     justify="center").pack()

    def _auto_detect_location(self):
        def worker():
            city = detect_location_by_ip()
            if city:
                self.after(0, self._prefill_and_search, city)

        threading.Thread(target=worker, daemon=True).start()

    def _prefill_and_search(self, city):
        self.city_entry.delete(0, tk.END)
        self.city_entry.insert(0, city)
        self.on_get_weather()


def main():
    app = WeatherApp()
    app.mainloop()


if __name__ == "__main__":
    main()
