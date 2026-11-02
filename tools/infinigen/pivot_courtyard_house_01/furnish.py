"""Invoke production realization with this scene's manual plans authoritative."""
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from room_planner import realize
import activity_pass_infinigen2 as activity

# All furniture/fixtures are explicitly specified in fixed plans. A bath and its
# adjacent dedicated WC must not each receive an automatic full bathroom set.
realize.RoomRealizer.REQUIRED_ITEMS={}
realize.RoomRealizer.REQUIRED_ZONE={}
if __name__=='__main__':
 activity.main()
