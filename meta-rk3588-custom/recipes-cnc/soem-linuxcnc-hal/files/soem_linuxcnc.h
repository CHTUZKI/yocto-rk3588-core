/**
 * SOEM EtherCAT glue for LinuxCNC (based on hieplchan/ethercat_soem_linuxcnc).
 */
#ifndef SOEM_LINUXCNC_H
#define SOEM_LINUXCNC_H

#include <stdint.h>
#include <ethercat.h>

extern char IOmap[4096];
extern int wkc;

struct Ethercat_set_value {
	uint8_t LED;
	int16_t set_position[7];
	int16_t set_velocity[7];
	int16_t set_torque[7];
};

struct Ethercat_actual_value {
	uint8_t button;
	int16_t actual_position[7];
	int16_t actual_velocity[7];
	int16_t actual_torque[7];
};

int init_ethercat(const char *ifname);
void shutdown_ethercat(void);

void set_output_byte(uint16_t slave_no, uint8_t byte_no, uint8_t value);
void set_output_uint16(uint16_t slave_no, uint8_t byte_no, uint16_t value);
void set_output_int16(uint16_t slave_no, uint8_t byte_no, int16_t value);

uint8_t get_input_byte(uint16_t slave_no, uint8_t byte_no);
uint16_t get_input_uint16(uint16_t slave_no, uint8_t byte_no);
int16_t get_input_int16(uint16_t slave_no, uint8_t byte_no);

struct Ethercat_actual_value get_process_value(void);
void set_process_value(struct Ethercat_set_value set_value);
struct Ethercat_actual_value ethecat_process_data(struct Ethercat_set_value set_value);

#endif
