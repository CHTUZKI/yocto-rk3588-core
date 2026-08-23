#include "soem_linuxcnc.h"

#include <stdio.h>
#include <string.h>

char IOmap[4096];
int wkc;
static int ethercat_ready;

int init_ethercat(const char *ifname)
{
	int oloop, iloop;

	if (ethercat_ready)
		return 0;

	if (!ifname || !ifname[0])
		return -1;

	if (!ec_init(ifname))
		return -1;

	if (ec_config_init(FALSE) <= 0)
		return -1;

	ec_config_map(&IOmap);
	ec_configdc();

	ec_statecheck(0, EC_STATE_SAFE_OP, EC_TIMEOUTSTATE * 4);

	oloop = ec_slave[0].Obytes;
	if ((oloop == 0) && (ec_slave[0].Obits > 0))
		oloop = 1;
	if (oloop > 8)
		oloop = 8;
	iloop = ec_slave[0].Ibytes;
	if ((iloop == 0) && (ec_slave[0].Ibits > 0))
		iloop = 1;
	if (iloop > 8)
		iloop = 8;

	ec_slave[0].state = EC_STATE_OPERATIONAL;
	ec_send_processdata();
	ec_receive_processdata(EC_TIMEOUTRET);
	ec_writestate(0);

	do {
		ec_send_processdata();
		ec_receive_processdata(EC_TIMEOUTRET);
		ec_statecheck(0, EC_STATE_OPERATIONAL, 50000);
	} while (ec_slave[0].state != EC_STATE_OPERATIONAL);

	ethercat_ready = 1;
	return 0;
}

void shutdown_ethercat(void)
{
	if (!ethercat_ready)
		return;

	ec_close();
	ethercat_ready = 0;
}

void set_output_byte(uint16_t slave_no, uint8_t byte_no, uint8_t value)
{
	uint8_t *data_ptr = ec_slave[slave_no].outputs + byte_no;
	*data_ptr = value;
}

void set_output_uint16(uint16_t slave_no, uint8_t byte_no, uint16_t value)
{
	uint8_t *data_ptr = ec_slave[slave_no].outputs + byte_no;
	*data_ptr++ = (value >> 0) & 0xFF;
	*data_ptr = (value >> 8) & 0xFF;
}

void set_output_int16(uint16_t slave_no, uint8_t byte_no, int16_t value)
{
	set_output_uint16(slave_no, byte_no, (uint16_t)value);
}

uint8_t get_input_byte(uint16_t slave_no, uint8_t byte_no)
{
	return ec_slave[slave_no].inputs[byte_no];
}

uint16_t get_input_uint16(uint16_t slave_no, uint8_t byte_no)
{
	uint16_t *u16 = (uint16_t *)(ec_slave[slave_no].inputs + byte_no);
	return *u16;
}

int16_t get_input_int16(uint16_t slave_no, uint8_t byte_no)
{
	return (int16_t)get_input_uint16(slave_no, byte_no);
}

struct Ethercat_actual_value get_process_value(void)
{
	struct Ethercat_actual_value get_data;

	get_data.button = get_input_byte(0, 0x2A);
	for (int i = 0; i < 7; i++) {
		get_data.actual_position[i] = get_input_int16(0, 0x00 + i * 2);
		get_data.actual_velocity[i] = get_input_int16(0, 0x0E + i * 2);
		get_data.actual_torque[i] = get_input_int16(0, 0x1C + i * 2);
	}
	return get_data;
}

void set_process_value(struct Ethercat_set_value set_value)
{
	set_output_byte(0, 0x2A, set_value.LED);
	for (int i = 0; i < 7; i++) {
		set_output_int16(0, 0x00 + i * 2, set_value.set_position[i]);
		set_output_int16(0, 0x0E + i * 2, set_value.set_velocity[i]);
		set_output_int16(0, 0x1C + i * 2, set_value.set_torque[i]);
	}
}

struct Ethercat_actual_value ethecat_process_data(struct Ethercat_set_value set_value)
{
	struct Ethercat_actual_value get_data;

	set_process_value(set_value);
	ec_send_processdata();
	wkc = ec_receive_processdata(EC_TIMEOUTRET);
	return get_process_value();
}
