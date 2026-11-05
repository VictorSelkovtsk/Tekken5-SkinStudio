from pathlib import Path
import argparse
import sys
import traceback

root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root))
parser=argparse.ArgumentParser(add_help=False)
parser.add_argument('--home',default=str(root))
args,_=parser.parse_known_args()
home=Path(args.home).resolve()
if '--home' not in sys.argv and not any(arg.startswith('--home=') for arg in sys.argv):sys.argv.extend(['--home',str(home)])
home.mkdir(parents=True,exist_ok=True)
sys.stdout=(home/'launcher.log').open('a',encoding='utf8',buffering=1)
sys.stderr=sys.stdout
try:
    from tools.skins_t5.studio import main
    main()
except Exception:
    traceback.print_exc()
    import ctypes
    ctypes.windll.user32.MessageBoxW(None,'Não foi possível abrir o Skin Studio.\nConsulte '+str(home/'launcher.log'),
                                   'Tekken 5 Skin Studio',0x10)
