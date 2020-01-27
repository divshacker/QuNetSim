import sys
import time
import numpy as np
import random

sys.path.append("../..")
from components.host import Host
from components.network import Network
from objects.daemon_thread import DaemonThread
from objects.qubit import Qubit
from backends.eqsn_backend import EQSNBackend

wait_time = 10

from components.logger import Logger

Logger.DISABLED = True


# helper function. Used get the next message with a sequence number. It ignores ACK
#                  messages and messages with other seq numbers.
def get_next_classical_message(host, receive_from_id, buffer, sequence_nr):
    buffer = buffer + host.get_classical(receive_from_id, wait=wait_time)
    msg = "ACK"
    while msg == "ACK" or (msg.split(':')[0] != ("%d" % sequence_nr)):
        if len(buffer) == 0:
            buffer = buffer + host.get_classical(receive_from_id, wait=wait_time)
        ele = buffer.pop(0)
        msg = ele.content
    return msg


# !! Warning: this Crypto algorithm is really bad!
# !! Warning: Do not use it as a real Crypto Algorithm!

# key has to be a string
def encrypt(key, text):
    encrypted_text = ""
    for char in text:
        encrypted_text += chr(ord(key) ^ ord(char))
    return encrypted_text


def decrypt(key, encrypted_text):
    return encrypt(key, encrypted_text)


def Alice_qkd(alice, msg_buff, secret_key, hosts):
    sequence_nr = 0
    # iterate over all bits in the secret key.
    for bit in secret_key:
        ack = False
        while not ack:
            print("Alice sequence nr is %d." % sequence_nr)
            # get a random base. 0 for Z base and 1 for X base.
            base = random.randint(0, 1)

            # create qubit
            q_bit = Qubit(alice)

            # Set qubit to the bit from the secret key.
            if bit == 1:
                q_bit.X()

            # Apply basis change to the bit if necessary.
            if base == 1:
                q_bit.H()

            # Send Qubit to Bob
            alice.send_qubit(hosts['Eve'].host_id, q_bit, await_ack=True)

            # Get measured basis of Bob
            message = get_next_classical_message(alice, hosts['Eve'].host_id, msg_buff, sequence_nr)

            # Compare to send basis, if same, answer with 0 and set ack True and go to next bit,
            # otherwise, send 1 and repeat.
            if message == ("%d:%d") % (sequence_nr, base):
                ack = True
                alice.send_classical(hosts['Eve'].host_id, ("%d:0" % sequence_nr), await_ack=True)
            else:
                ack = False
                alice.send_classical(hosts['Eve'].host_id, ("%d:1" % sequence_nr), await_ack=True)

            sequence_nr += 1


def Eve_qkd(bob, msg_buff, key_size, hosts):
    eve_key = None

    sequence_nr = 0
    received_counter = 0
    key_array = []

    while received_counter < key_size:
        print("received counter is %d." % received_counter)
        print("Eve sequence nr is %d." % sequence_nr)

        # decide for a measurement base
        measurement_base = random.randint(0, 1)

        # wait for the qubit
        q_bit = bob.get_data_qubit(hosts['Alice'].host_id, wait=wait_time)
        while q_bit is None:
            q_bit = bob.get_data_qubit(hosts['Alice'].host_id, wait=wait_time)

        # measure qubit in right measurement basis
        if measurement_base == 1:
            q_bit.H()
        bit = q_bit.measure()

        # Send Alice the base in which Bob has measured
        bob.send_classical(hosts['Alice'].host_id, "%d:%d" % (sequence_nr, measurement_base), await_ack=True)

        # get the return message from Alice, to know if the bases have matched
        msg = get_next_classical_message(bob, hosts['Alice'].host_id, msg_buff, sequence_nr)

        # Check if the bases have matched
        if msg == ("%d:0" % sequence_nr):
            received_counter += 1
            key_array.append(bit)
        sequence_nr += 1

    eve_key = key_array

    return eve_key


# helper function, used to make your key to a string
def key_array_to_key_string(key_array):
    key_string_binary = ''.join([str(x) for x in key_array])
    return ''.join(chr(int(''.join(x), 2)) for x in zip(*[iter(key_string_binary)] * 8))


def Alice_send_message(alice, msg_buff, secret_key, hosts):
    msg_to_eve = "Hi Eve, I am your biggest fangirl! Unfortunately you only exist as a computer protocol :("

    secret_key_string = key_array_to_key_string(secret_key)
    encrypted_msg_to_eve = encrypt(secret_key_string, msg_to_eve)
    alice.send_classical(hosts['Eve'].host_id, "-1:" + encrypted_msg_to_eve, await_ack=True)


def Eve_receive_message(eve, msg_buff, eve_key, hosts):
    decrypted_msg_from_alice = None

    encrypted_msg_from_alice = get_next_classical_message(eve, hosts['Alice'].host_id, msg_buff, -1)
    encrypted_msg_from_alice = encrypted_msg_from_alice.split(':')[1]
    secret_key_string = key_array_to_key_string(eve_key)
    decrypted_msg_from_alice = decrypt(secret_key_string, encrypted_msg_from_alice)

    print("Eve: Alice told me %s I am so happy!" % decrypted_msg_from_alice)


def main():
    # Create EQSN backend
    backend = EQSNBackend()

    # Initialize a network
    network = Network.get_instance()

    # Define the host IDs in the network
    nodes = ['Alice', 'Bob', 'Eve']

    network.delay = 0.0

    # Start the network with the defined hosts
    network.start(nodes, backend)

    # Initialize the host Alice
    host_alice = Host('Alice', backend)

    # Add a one-way connection (classical and quantum) to Bob
    host_alice.add_connection('Bob')

    # Start listening
    host_alice.start()

    host_bob = Host('Bob', backend)
    # Bob adds his own one-way connection to Alice and Eve
    host_bob.add_connection('Alice')
    host_bob.add_connection('Eve')
    host_bob.start()

    host_eve = Host('Eve', backend)
    host_eve.add_connection('Bob')
    host_eve.start()

    # Add the hosts to the network
    # The network is: Alice <--> Bob <--> Eve
    network.add_host(host_alice)
    network.add_host(host_bob)
    network.add_host(host_eve)

    # Generate random key
    key_size = 8  # the size of the key in bit
    secret_key = np.random.randint(2, size=key_size)

    hosts = {'Alice': host_alice,
             'Bob': host_bob,
             'Eve': host_eve}

    # Concatentate functions
    def Alice_func(alice=host_alice):
        msg_buff = []
        Alice_qkd(alice, msg_buff, secret_key, hosts)
        Alice_send_message(alice, msg_buff, secret_key, hosts)

    def Eve_func(eve=host_eve):
        msg_buff = []
        eve_key = Eve_qkd(eve, msg_buff, key_size, hosts)
        Eve_receive_message(eve, msg_buff, eve_key, hosts)

    # Run Bob and Alice
    thread_alice = DaemonThread(Alice_func)
    thread_eve = DaemonThread(Eve_func)

    thread_alice.join()
    thread_eve.join()

    for h in hosts.values():
        h.stop()
    network.stop()


if __name__ == '__main__':
    main()