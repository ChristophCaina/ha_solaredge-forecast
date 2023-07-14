"""Module to make a forecast for the solar energy production"""
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import solaredge
import pandas as pd

class SolaredgeForecast(object):
    """Solaredge forecast data"""
    def __init__(self, startdate, enddate, startdate_production, site_id, account_key):
        self.startdate = datetime.strptime(startdate, '%Y%m%d').date()
        self.enddate = datetime.strptime(enddate, '%Y%m%d').date()
        self.site_id = site_id
        self.account_key = account_key
        if startdate_production:
            date = (datetime.strptime(startdate_production, '%d%m%Y'))
            if date.day > 1:
                date += relativedelta(months=1, day=1)
            self.startdate_production = date.date()
        else:
            self.startdate_production = startdate_production

        data = self.get_solar_forecast()

        self.solaredge_estimated = data["Solar energy estimated"]
        self.solaredge_produced = data["Solar energy produced"]
        self.solaredge_forecast = data["Solar energy forecast"]
        self.solaredge_progress = data["Solar energy progress"]

    def get_solar_forecast(self):
        """Calculate solar energy forecast."""
        now = datetime.now()
        yesterday = now.date() - timedelta(days=1)
        today = now.date()
        tomorrow = now.date() + timedelta(days=1)
        last_month = now.date().replace(day=1) - timedelta(days=1)

        # connect to Solaredge API
        data = solaredge.Solaredge(self.account_key)

        # Get date when production started
        if not self.startdate_production:
            start_production = data.get_data_period(site_id=self.site_id)["dataPeriod"]["startDate"]
            self.startdate_production = (datetime.strptime(start_production, "%Y-%m-%d")
                                         + relativedelta(months=1, day=1)).date()

        # Get energy production per month from production start until now and store in dataframe
        energy_month_average = data.get_energy(site_id=self.site_id,
                                               start_date=self.startdate_production,
                                               end_date=last_month,
                                               time_unit="MONTH")
        # create dataframe with values per month
        df = pd.DataFrame(energy_month_average['energy']['values'])
        df.rename(columns={'value': 'energy'}, inplace=True)
        df = df[df.energy != 0]
        df['date'] = pd.to_datetime(df['date'])
        df['year'] = df.date.dt.year
        df['month'] = df.date.dt.month
        df['days_in_month'] = df.date.dt.days_in_month
        # change wh to Kwh
        df['energy'] = df.energy / df.days_in_month / 1000
        # create series of monthly averages
        averages = df.groupby(df.date.dt.month)['energy'].mean()

        # create dataframe with all days between startdate - 1 month and enddate + 1 month
        daily = pd.DataFrame(
            pd.date_range(start=self.startdate - relativedelta(months=1), end=self.enddate + relativedelta(months=1)),
            columns=['date'])
        daily = daily.set_index('date', drop=False)
        daily['month'] = daily.date.dt.month
        daily['day'] = daily.date.dt.day

        # add average energy production per month for 1 day and store at the 15th day in the dataframe
        def average(row):
            """ function to return the daily average energy for a given month"""
            if row['day'] == 15:
                return averages[row["month"]]
        daily['energy'] = daily.apply(average, axis=1)

        # interpolate between the 15th day of each month
        daily = daily.interpolate(limit_direction='both')

        energy_estimated_from_tomorrow = daily.loc[tomorrow:self.enddate]['energy'].sum()
        energy_estimated_until_yesterday = daily.loc[self.startdate:yesterday]['energy'].sum()
        energy_estimated_today = daily.loc[today:today]['energy'].sum()
        energy_estimated_period = energy_estimated_today + energy_estimated_from_tomorrow

        # Calculated produced energy from start until today
        energy_production_until_now = data.get_time_frame_energy(site_id=self.site_id,
                                                                start_date=self.startdate,
                                                                end_date=self.enddate,
                                                                time_unit="YEAR")['timeFrameEnergy']['energy'] / 1000
        # Get produced energy today
        energy_produced_today = data.get_time_frame_energy(site_id=self.site_id,
                                                           start_date=now.date(),
                                                           end_date=tomorrow,
                                                           time_unit="day")['timeFrameEnergy']['energy'] / 1000

        energy_produced_until_yesterday = energy_production_until_now - energy_produced_today
        energy_produced_today_extra = max(0, energy_produced_today - energy_estimated_today)

        # calculate the progress of the currently produced energy in relation to the forecast. A positive value means
        # that the produced energy is ahead of forecast, a negative value means that it is behind forecast
        energy_production_progress = energy_produced_until_yesterday - energy_estimated_until_yesterday\
                                     + energy_produced_today_extra

        # Calculate the total estimated energy production
        forecast = energy_estimated_period + energy_production_until_now

        data = {}
        data["Solar energy produced"] = round(energy_production_until_now)
        data["Solar energy estimated"] = round(energy_estimated_period)
        data["Solar energy forecast"] = round(forecast)
        data["Solar energy progress"] = round(energy_production_progress)

        return data
