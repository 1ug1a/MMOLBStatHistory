# mmolb stat history
in lieu of freecashe.ws not currently having stat trendlines at the moment i made this (thank you freecashe.ws devs for the api! i tried to minimize the number of API requests though that's kinda hard when you have to get data from across an entire season orz)

# features:
- show various stats of a single player
- show a single stat across an entire team's pitchers or batters
- choose which season and range of days to visualize
- adjust the rolling average applied to the data to your liking
- parallel api requests (at a hopefully reasonable amount) and network caching (!!!!!)

# how to use
1. install python (3.13.0 or higher)
2. open a terminal in the folder that contains `MMOLBStatHistory.py`
3. run `pip install -r requirements.txt`
4. adjust the various settings in the file (stat mode, ids, etc.)
5. run `python MMOLBStatHistory.py`
