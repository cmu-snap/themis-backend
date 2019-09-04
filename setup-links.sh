# setup link for module_msg.proto into bess folder
ln --symbolic \
   --force \
   --verbose \
   --target-directory=/opt/bess/protobuf/ \
   /opt/cctestbed/module_msg.proto

# setup links for queue_delay module into bess folder
ln --symbolic \
   --force \
   --verbose \
   --target-directory=/opt/bess/core/modules/ \
   /opt/cctestbed/queue_delay.cc

ln --symbolic \
   --force \
   --verbose \
   --target-directory=/opt/bess/core/modules/ \
   /opt/cctestbed/queue_delay.h

# setup links for queue_delay test config file into bess folder
ln --symbolic \
   --force \
   --verbose \
   --target-directory=/opt/bess/bessctl/conf/ \
   /opt/cctestbed/test_queue_delay.bess

# setup links for active-middlebox-pmd config file into bess folder
ln --symbolic \
   --force \
   --verbose \
   --target-directory=/opt/bess/bessctl/conf/ \
   /opt/cctestbed/active-middlebox-pmd.bess

# setup links for queue_module
ln --symbolic \
   --force \
   --verbose \
   --target-directory=/opt/bess/core/modules/ \
   /opt/cctestbed/queue.cc

ln --symbolic \
   --force \
   --verbose \
   --target-directory=/opt/bess/core/modules/ \
   /opt/cctestbed/queue.h
 
# setup links for timestamp module (can use built in header file)
ln --symbolic \
   --force \
   --verbose \
   --target-directory=/opt/bess/core/modules/ \
   /opt/cctestbed/timestamp.cc

ln --symbolic \
   --force \
   --verbose \
   --target-directory=/opt/bess/core/modules/ \
   /opt/cctestbed/timestamp.h

# setup links for the port match module
ln --symbolic \
   --force \
   --verbose \
   --target-directory=/opt/bess/core/modules/ \
   /opt/cctestbed/port_match.h

ln --symbolic \
   --force \
   --verbose \
   --target-directory=/opt/bess/core/modules/ \
   /opt/cctestbed/port_match.cc


# setup links for active-middlebox-pmd config file into bess folder
ln --symbolic \
   --force \
   --verbose \
   --target-directory=/opt/bess/bessctl/conf/ \
   /opt/cctestbed/active-middlebox-pmd-fairness.bess
