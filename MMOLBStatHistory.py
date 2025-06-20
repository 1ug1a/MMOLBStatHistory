import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
import pandas as pd

from aiohttp_client_cache import CachedSession, SQLiteBackend
import asyncio

from inspect import getsourcefile
from pathlib import Path

# mmolb stat history by dusk (@1ug1a)

STAT_MODE = 'Player' # 'Player' (uses PLAYER_ID), 'Batters', or 'Pitchers' (uses TEAM_ID)
PLAYER_ID = '680c69a6ecda7a92d4c14cb8'
TEAM_ID = '6805db0cac48194de3cd40b5'

SEASON_NUM = 1
DAY_START = 1
DAY_END = 231

ROLLING_AVG_WINDOW = 5

SOLO_BATTING_STATS = ['ba', 'obp', 'slg', 'ops', 'babip', 'bb_p', 'k_p', 'sb_p']
SOLO_PITCHING_STATS = ['era', 'fip_r', 'whip', 'h9', 'hr9', 'k9', 'bb9', 'kpbb']
USE_SOLO_CUSTOM_STATS = False
SOLO_CUSTOM_STATS = ['ops',  'era']

TEAM_BATTER_STAT = 'ops'
TEAM_PITCHER_STAT = 'era'

MAX_CONNECTIONS = 4
SCRIPT_PATH = Path(getsourcefile(lambda: 0)).resolve()
DB_PATH = SCRIPT_PATH.parent / 'MMOLBStatHistory.db'

CACHE = SQLiteBackend(
  cache_name=DB_PATH,  # For SQLite, this will be used as the filename
  expire_after=60*25,                         
)

# info-gathering
def get_player_info_lite(p_id):
  response = asyncio.run(get_urls(f'https://freecashe.ws/api/chron/v0/entities?kind=player_lite&id={p_id}'))
  #print(response['items'])
  response = response['items'][0]['data'] if len(response['items']) != 0 else {}
  return response

def get_team_info_lite(t_id):
  response = asyncio.run(get_urls(f'https://freecashe.ws/api/chron/v0/entities?kind=team_lite&id={t_id}'))
  #print(response['items'])
  response = response['items'][0]['data'] if len(response['items']) != 0 else {}
  return response

def get_player_id_dict(t_info):
  player_list = t_info['Players']
  players = {}
  for player in player_list:
    players[player['PlayerID']] = player
  return players

def parse_player_feed(p_info, season_num, day_start, day_end):
  feed = p_info['Feed']
  parsed_feed = {}
  for entry in feed:
    if entry['season'] == season_num and (day_start <= entry['day'] <= day_end) and entry['type'] == 'augment':
      parsed_feed[entry['day']] = entry['text']
  return parsed_feed

def parse_team_feed(t_info, season_num, day_start, day_end):
  feed = t_info['Feed']
  parsed_feed = {}
  for entry in feed:
    if entry['season'] == season_num and isinstance(entry['day'], int) and (day_start <= entry['day'] <= day_end) and entry['type'] == 'augment':
      parsed_feed[entry['day']] = entry['text']
  return parsed_feed

def get_player_stat_history(p_id, season_num, day_start, day_end):
  history = {}
  api_urls = []
  print('Gathering player stat history...')
  for day in range(day_start, day_end+1, 2):
    api_urls.append(f'https://freecashe.ws/api/player-stats?player={p_id}&start={season_num},0&end={season_num},{day}')
    history[day] = {}
  api_data = asyncio.run(get_urls(api_urls, MAX_CONNECTIONS))
  i = 0
  for day in history.keys():
    history[day] = api_data[i][0]['stats'] if api_data[i] else {}
    #print(f'{day}: {history[day]}')
    i = i+1
  print('Done!')
  return history

def get_team_stat_history(t_id, t_dict, stat_mode, season_num, day_start, day_end):
  history = {}
  api_urls = []
  print('Gathering team stat history...')
  for day in range(day_start, day_end+1, 2):
    api_urls.append(f'https://freecashe.ws/api/player-stats?team={t_id}&start={season_num},0&end={season_num},{day}')
    history[day] = {}
  api_data = asyncio.run(get_urls(api_urls, MAX_CONNECTIONS))
  i = 0
  # wow this is a mess
  temp_data = {}
  for day in history.keys():
    temp_data.clear()
    #print(api_data)
    for stat_block in api_data[i]:
      temp_data[stat_block['player_id']] = stat_block['stats']
    #print()
    history[day].update(temp_data) if temp_data else {}
    #print(f'{day}: {history[day]}')
    i = i+1
  player_history = {}
  for player_id in t_dict:
    # print(t_dict[player_id]['PositionType'], t_dict[player_id]['PositionType'] == stat_mode[:-1])
    if t_dict[player_id]['PositionType'] == stat_mode[:-1]:
      player_history[player_id] = {}
  for day, stat_block in history.items():
    #print(day)
    #print(stat_block)
    for player_id, stats in stat_block.items():
      if player_id in t_dict:
        if t_dict[player_id]['PositionType'] == stat_mode[:-1]:
          player_history[player_id].update({day: stats})

  print('Done!')
  return player_history

async def get_url(session, url, semaphore):
  async with semaphore:
    async with session.get(url) as response:
      return await response.json()

async def get_urls(urls, max_con_req=1):
  single_flag = False
  if not isinstance(urls, list):
    urls = [urls]
    single_flag = True
  semaphore = asyncio.Semaphore(max_con_req)
  async with CachedSession(cache=CACHE) as session:
    tasks = [get_url(session, url, semaphore) for url in urls]
    result = await asyncio.gather(*tasks)
    if single_flag:
      return result[0]
    else:
      return result

def parse_team_stat_history(t_history, t_dict):
  parsed_team_history = {}
  for p_id, p_history in t_history.items():
    
    parsed_team_history[p_id] = parse_player_stat_history(p_history, t_dict[p_id])
  return parsed_team_history

def parse_player_stat_history(p_history, p_info):
  p_pos_type = p_info['PositionType']
  parsed_history = {}
  for key, value in p_history.items():
    if p_pos_type == 'Pitcher':
      parsed_history[key] = parse_player_stats_pitcher(value)
    elif p_pos_type == 'Batter':
      parsed_history[key] = parse_player_stats_batter(value)
  return parsed_history

def parse_player_stats_batter(p_stats):
  _pa   = p_stats.get('plate_appearances', 0)
  _ab   = p_stats.get('at_bats', 0)
  _1b   = p_stats.get('singles', 0)
  _2b   = p_stats.get('doubles', 0)
  _3b   = p_stats.get('triples', 0)
  _hr   = p_stats.get('home_runs', 0)
  _h    = _1b + _2b + _3b + _hr
  _bb   = p_stats.get('walked', 0)
  _hbp  = p_stats.get('hit_by_pitch', 0)
  _k    = p_stats.get('struck_out', 0)
  _sf   = p_stats.get('sac_flies', 0)
  _sb   = p_stats.get('stolen_bases', 0)
  _cs   = p_stats.get('caught_stealing', 0)

  ba    = _h / _ab if _ab != 0 else np.nan
  obp   = (_h + _bb + _hbp) / _pa if _pa != 0 else np.nan
  slg   = (_1b + 2*_2b + 3*_3b + 4*_hr) / _ab if _ab != 0 else np.nan
  ops   = obp + slg
  babip = (_h - _hr) / (_ab - _hr - _k + _sf) if (_ab - _hr - _k + _sf) != 0 else np.nan
  bb_p  = _bb / _pa if _pa != 0 else np.nan
  k_p   = _k / _pa if _pa != 0 else np.nan
  sb_p  = _sb / (_sb + _cs) if (_sb + _cs) != 0 else np.nan

  stats = {}
  stats_used = list(set(SOLO_BATTING_STATS) & set(SOLO_CUSTOM_STATS)) if USE_SOLO_CUSTOM_STATS else SOLO_BATTING_STATS
  for i in stats_used:
    stats[i] = locals()[i]

  return stats

def parse_player_stats_pitcher(p_stats):
  _ip   = p_stats.get('outs', 0)/3
  _h    = p_stats.get('hits_allowed', 0)
  _hr   = p_stats.get('home_runs_allowed', 0)
  _k    = p_stats.get('strikeouts', 0)
  _bb   = p_stats.get('walks', 0)
  _er   = p_stats.get('earned_runs', 0)
  _hb   = p_stats.get('hit_batters', 0)
  
  era   = 9*_er / _ip if _ip != 0 else np.nan
  fip_r = (13*_hr + 3*(_bb + _hb) - 2*_k) / _ip if _ip != 0 else np.nan
  whip  = (_h + _bb) / _ip if _ip != 0 else np.nan
  h9    = 9*_h / _ip if _ip != 0 else np.nan
  hr9   = 9*_hr / _ip if _ip != 0 else np.nan
  k9    = 9*_k / _ip if _ip != 0 else np.nan
  bb9   = 9*_bb / _ip if _ip != 0 else np.nan
  kpbb  = _k / _bb if _bb != 0 else np.nan

  stats = {}
  stats_used = list(set(SOLO_PITCHING_STATS) & set(SOLO_CUSTOM_STATS)) if USE_SOLO_CUSTOM_STATS else SOLO_PITCHING_STATS
  for i in stats_used:
    stats[i] = locals()[i]

  return stats

def plot_team_stats(t_parsed, t_info, t_dict, t_feed, day_start, day_end, stat_mode):
  day_numbers = np.arange(day_start, day_end)
  p_ids = list(t_parsed.keys())
  player_labels = {p_id: f'{t_dict[p_id]['Position']} {t_dict[p_id]['FirstName']} {t_dict[p_id]['LastName']}' for p_id in p_ids}

  if stat_mode == 'Batters':
    stat = TEAM_BATTER_STAT
  elif stat_mode == 'Pitchers':
    stat = TEAM_PITCHER_STAT

  plots = {}
  for p_id in p_ids:
    plots[p_id] = []
  for p_id, history in t_parsed.items():
    for day in day_numbers:
      if day in history:
        plots[p_id].append(history[day][stat])
      else:
        plots[p_id].append(np.nan)

  # this feels really inefficient but this fixes the rolling mean stuff
  updated_days = []
  updated_plots = {}
  for p_id, value in plots.items():
    updated_plots[p_id] = []

  for index, day in enumerate(day_numbers):
    all_nan = True
    for p_id, value in plots.items():
      if not np.isnan(value[index]):
        all_nan = False
    if not all_nan:
      updated_days.append(day)
      for p_id, value in plots.items():
        updated_plots[p_id].append(value[index])

  means = {}
  for p_id in p_ids:
    means[p_id] = pd.Series(updated_plots[p_id]).rolling(window=ROLLING_AVG_WINDOW, min_periods=1, center=True).mean()

  fig, ax = plt.subplots(layout="constrained", figsize=(12, 6))

  #print(day_numbers)
  #print(stat_labels)
  for p_id in p_ids:
    ax.plot(updated_days, means[p_id], label = player_labels[p_id])
    #print(stat_arrays[stat])

  t_name = f'{t_info['Location']} {t_info['Name']}'

  ax.set_xlabel('Day')
  ax.set_xlim(left=day_start, right=day_end)
  ax.set_xticks(np.arange(day_start, day_end))
  ax.set_title(f'{t_name} {stat_mode[:-3] + "ing"} History ({stat.upper()})')
  ax.grid(which='major', color='#999999', linewidth=0.8)
  ax.grid(which='minor', color='#CCCCCC', linestyle=':', linewidth=0.5)
  ax.minorticks_on()
  ax.legend()

  text = ''
  for day in t_feed:
    text += f'Day {day}: {t_feed[day]}\n'
    ax.axvline(x=day, color='gray', linestyle='--', label=t_feed[day])
  text = text.rstrip('\n')
  print(text)

  ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))

  plt.show()

def plot_solo_stats(p_statlines, p_info, t_info, p_feed, day_start, day_end):
  day_numbers = list(p_statlines.keys()) # x values
  stat_labels = list(next(iter(p_statlines.values())).keys())
  stat_arrays = {}
  for stat in stat_labels:
    stat_arrays[stat] = []
  for key, val in p_statlines.items():
    for stat in stat_labels:
      stat_arrays[stat].append(val[stat])
  mean_arrays = {}
  for stat in stat_labels:
    mean_arrays[stat] = pd.Series(stat_arrays[stat]).rolling(window=ROLLING_AVG_WINDOW, min_periods=1, center=True).mean()

  fig, ax = plt.subplots(layout="constrained", figsize=(12, 6))

  #print(day_numbers)
  #print(stat_labels)
  for stat in stat_labels:
    ax.plot(day_numbers, mean_arrays[stat], label = stat)
    #print(stat_arrays[stat])

  p_name = f'{p_info['FirstName']} {p_info['LastName']}'
  p_pos_type = p_info['PositionType'][:-2]+'ing'
  t_name = f'{t_info['Location']} {t_info['Name']}'

  ax.set_xlabel('Day')
  ax.set_xlim(left=day_start, right=day_end)
  ax.set_xticks(np.arange(day_start, day_end))
  ax.set_title(f'{p_name} ({t_name}) {p_pos_type} History')
  ax.grid(which='major', color='#999999', linewidth=0.8)
  ax.grid(which='minor', color='#CCCCCC', linestyle=':', linewidth=0.5)
  ax.minorticks_on()
  ax.legend()

  ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))

  text = ''
  for day in p_feed:
    text += f'Day {day}: {p_feed[day]}\n'
    ax.axvline(x=day, color='gray', linestyle='--', label=p_feed[day])
  text = text.rstrip('\n')
  #print(text)

  ax.annotate(text,
              xy = (0, -50),
              xycoords = 'axes pixels',
              va = 'top')

  plt.show()

def main():
  if STAT_MODE == 'Player':
    p_info = get_player_info_lite(PLAYER_ID)
    if p_info == {}:
      print('Invalid player ID.')
      exit()
    t_id = p_info['TeamID']
    t_info = get_team_info_lite(t_id)
    p_history = get_player_stat_history(PLAYER_ID, SEASON_NUM, DAY_START, DAY_END)
    #print(p_history)
    p_statlines = parse_player_stat_history(p_history, p_info)
    #print(p_statlines)
    p_feed = parse_player_feed(p_info, SEASON_NUM, DAY_START, DAY_END)
    plot_solo_stats(p_statlines, p_info, t_info, p_feed, DAY_START, DAY_END)
  else:
    t_info = get_team_info_lite(TEAM_ID)
    if t_info == {}:
      print('Invalid team ID.')
      exit()
    t_dict = get_player_id_dict(t_info)
    #print(t_dict)
    t_history = get_team_stat_history(TEAM_ID, t_dict, STAT_MODE, SEASON_NUM, DAY_START, DAY_END)
    t_parsed = parse_team_stat_history(t_history, t_dict)
    #for player_id in t_parsed:
      #print(player_id)
      #print(t_parsed[player_id])
    t_feed = parse_team_feed(t_info, SEASON_NUM, DAY_START, DAY_END)
    plot_team_stats(t_parsed, t_info, t_dict, t_feed, DAY_START, DAY_END, STAT_MODE)

if __name__ == '__main__':
  main()