import React from 'react';

const MissionsTab = ({ missions }) => {
  return (
    <div className="tabContent">
      <div className="missionList">
        {missions.map((m, idx) => (
          <div key={idx} className="missionCard">
            <b>{m.name || m}</b>
            {m.desc && <p>{m.desc}</p>}
          </div>
        ))}
      </div>
    </div>
  );
};

export default MissionsTab;