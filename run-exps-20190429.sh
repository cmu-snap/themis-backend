for i in $(seq 1 20)
do
    python3.6 ccalg_fairness.py --test iperf-website --test iperf16-website --test apache-website --website asset-intertech.com "https://www.asset-intertech.com/sites/default/files/media/scanworks-bst-basics.mp4" --duration 240 --num_competing 1 --competing_ccalg cubic --network 10 75 32 --network 10 75 64 --network 10 75 512

    python3.6 ccalg_fairness.py --test video-website --website kingsoftstore.com "http://www.kingsoftstore.com/download/setup_wps_office_2016_business.exe" --duration 240 --num_competing 1 --competing_ccalg cubic --network 5 75 16 --network 5 75 32 --network 5 75 256

    python3.6 ccalg_fairness.py --test video-website --website asset-intertech.com "https://www.asset-intertech.com/sites/default/files/media/scanworks-bst-basics.mp4" --duration 240 --num_competing 1 --competing_ccalg cubic --network 5 75 16 --network 5 75 32 --network 5 75 256

    python3.6 ccalg_fairness.py --test iperf-website --test iperf16-website --test apache-website --website cypress.io "https://cdn.cypress.io/desktop/3.1.0/osx64/cypress.zip" --duration 240 --num_competing 1 --competing_ccalg cubic --network 10 75 32 --network 10 75 64 --network 10 75 512
done


