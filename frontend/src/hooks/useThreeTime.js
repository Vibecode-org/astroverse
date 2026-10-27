/** Time sync: update simTime from simDate (10 Hz time engine). */

import { useEffect } from 'react';

export function useThreeTime({ simDate, objects, appRef }) {
  useEffect(() => {
    appRef.current.simTime = simDate.getTime();
  }, [simDate, objects, appRef]);
}