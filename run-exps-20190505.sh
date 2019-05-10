for i in $(seq 1 10)
do
    python3.6 ccalg_fairness.py --test iperf-website --test iperf16-website --test apache-website --website ditchingsuburbia.com "https://ditchingsuburbia.com/podcast/BrandonCaveInterview.mp3" --duration 240 --num_competing 1 --competing_ccalg cubic --network 10 75 32 --network 10 75 64 --network 10 75 512

    python3.6 ccalg_fairness.py --test video-website --website ditchingsuburbia.com "https://ditchingsuburbia.com/podcast/BrandonCaveInterview.mp3" --duration 240 --num_competing 1 --competing_ccalg cubic --network 5 75 16 --network 5 75 32 --network 5 75 256
done


