#! /bin/bash

CCA="https://cca.org/on-copper-wings/on-copper-wings.mp4"
LINUX="http://www.linuxha.com/athome/common/2017-06-21-raspbian-jessie.zip"
CAPITAL="http://forums.capitallink.com/greece/2017/video/manuelides.mp4"
APPLE="https://www.apple.com/105/media/us/home/2018/da585964_d062_4b1d_97d1_af34b440fe37/films/behind-the-mac/mac-behind-the-mac-tpl-cc-us-2018_1280x720h.mp4"
BLS="https://www.bls.gov/oes/special.requests/oesm17all.zip" 
SSA="https://www.ssa.gov/pubs/audio/EN-05-10035.mp3"

python3.6 ccalg_predict.py --website ssa.gov $SSA --network 10 35 128
python3.6 ccalg_predict.py --website ssa.gov $SSA --network 20 35 128
python3.6 ccalg_predict.py --website ssa.gov $SSA --network 25 35 128
python3.6 ccalg_predict.py --website ssa.gov $SSA --network 15 35 32
python3.6 ccalg_predict.py --website ssa.gov $SSA --network 15 35 64
python3.6 ccalg_predict.py --website ssa.gov $SSA --network 15 35 128
python3.6 ccalg_predict.py --website ssa.gov $SSA --network 15 35 512

python3.6 ccalg_predict.py --website bls.gov $BLS --network 25 35 128
python3.6 ccalg_predict.py --website bls.gov $BLS --network 15 85 128
python3.6 ccalg_predict.py --website bls.gov $BLS --network 15 35 64
python3.6 ccalg_predict.py --website bls.gov $BLS --network 15 35 128

python3.6 ccalg_predict.py --website apple.com $APPLE --network 15 35 32
python3.6 ccalg_predict.py --website apple.com $APPLE --network 15 35 128
python3.6 ccalg_predict.py --website apple.com $APPLE --network 15 35 512

python3.6 ccalg_predict.py --website capitallink.com $CAPITAL --network 15 35 128

python3.6 ccalg_predict.py --website linuxha.com $LINUX --network 15 35 128

python3.6 ccalg_predict.py --website cca.org $CCA --network 15 35 512
