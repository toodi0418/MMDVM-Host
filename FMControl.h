/*
 *   Copyright (C) 2020,2021 by Jonathan Naylor G4KLX
 *
 *   This program is free software; you can redistribute it and/or modify
 *   it under the terms of the GNU General Public License as published by
 *   the Free Software Foundation; either version 2 of the License, or
 *   (at your option) any later version.
 *
 *   This program is distributed in the hope that it will be useful,
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *   GNU General Public License for more details.
 *
 *   You should have received a copy of the GNU General Public License
 *   along with this program; if not, write to the Free Software
 *   Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.
 */

#if !defined(FMControl_H)
#define	FMControl_H

#include "FMNetwork.h"
#include "Defines.h"
#include "IIRDirectForm1Filter.h"

// Uncomment this to dump audio to a raw audio file
// The file will be written in same folder as executable
// Toplay the file : ffplay -autoexit -f u16be -ar 8000 audiodump.bin
// #define DUMP_RF_AUDIO

// ---------------------------------------------------------------------------
// Squelch tail elimination (R1 customisation)
//
// The RF audio received from the modem is held in a fixed length delay line
// and released to the FM network slightly later than it arrives. When the
// modem reports the end of the RF transmission the audio still sitting in the
// delay line is thrown away instead of being sent, so the squelch tail noise
// produced while the carrier drops never reaches the network.
//
// The delay line is fixed size and the number of samples released always
// equals the number of samples received, so the network packet cadence is
// unchanged and no audio is ever sent in a burst.
// ---------------------------------------------------------------------------

const unsigned int FM_TAIL_ELIM_MIN_MS    = 20U;	// Smallest usable delay
const unsigned int FM_TAIL_ELIM_MAX_MS    = 500U;	// Largest usable delay
const unsigned int FM_TAIL_ELIM_RATE      = 8000U;	// FM audio sample rate in Hz
const unsigned int FM_TAIL_ELIM_MAX_FRAME = 160U;	// Max samples produced per writeModem() pass
const unsigned int FM_TAIL_ELIM_GAP_MS    = 300U;	// Silence that marks the start of a new transmission

class CFMControl {
public:
	CFMControl(CFMNetwork* network, float txAudioGain, float rxAudioGain, bool preEmphasisOn, bool deEmphasisOn, bool tailElimEnabled = false, unsigned int tailElimMs = 0U);
	~CFMControl();

	bool writeModem(const unsigned char* data, unsigned int length);

	unsigned int readModem(unsigned char* data, unsigned int space);

	void clock(unsigned int ms);

	void enable(bool enabled);

private:
	CFMNetwork* m_network;
	float       m_txAudioGain;
	float       m_rxAudioGain;
	bool        m_preEmphasisOn;
	bool        m_deEmphasisOn;
    bool        m_enabled;
	CRingBuffer<unsigned char> m_incomingRFAudio;
	CIIRDirectForm1Filter* m_preEmphasis;
	CIIRDirectForm1Filter* m_deEmphasis;
	CIIRDirectForm1Filter* m_filterStage1;
	CIIRDirectForm1Filter* m_filterStage2;
	CIIRDirectForm1Filter* m_filterStage3;

	// Squelch tail elimination state
	bool         m_tailElimEnabled;
	unsigned int m_tailElimMs;
	unsigned int m_delaySamples;
	unsigned int m_delayCapacity;
	float*       m_delayLine;
	unsigned int m_delayHead;
	unsigned int m_delayTail;
	unsigned int m_delayCount;
	bool         m_delayPrimed;
	unsigned int m_idleMs;
	bool         m_delayFaultLogged;

	void resetDelayLine();
	bool primeDelayLine();
	bool applyDelay(const float* in, unsigned int nIn, float* out, unsigned int& nOut);
};

#endif
