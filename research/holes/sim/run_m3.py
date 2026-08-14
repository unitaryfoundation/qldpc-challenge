import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from sim.schedule_search3 import search

# seed: the m=2 exhaustive optimum, junction left to chance
M2OPT = {'bulk': (0, 0), 'corrH': (1, 0), 'corrV': (0, 0),
         'ringXEW': (1, 0), 'ringXNS': (0, 0),
         'ringZEW': (0, 0), 'ringZNS': (0, 0)}

if __name__ == '__main__':
    search(h=2, mX=3, budget_hours=1.5, workers=7, init_assign=M2OPT)
