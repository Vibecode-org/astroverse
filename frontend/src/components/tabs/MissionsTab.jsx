import React from 'react';

const MissionsTab = ({ missions }) => {
  // missions может отсутствовать или прийти не-массивом: раньше здесь был
  // голый missions.map() без защиты, и один битый объект глушил всё приложение.
  const items = Array.isArray(missions) ? missions : [];
  return (
    <div className="tabContent">
      <div className="missionList">
        {items.map((m, idx) => (
          <div key={idx} className="missionCard">
            <b>{typeof m === 'string' ? m : m?.name}</b>
            {typeof m === 'object' && m?.desc && <p>{m.desc}</p>}
          </div>
        ))}
      </div>
    </div>
  );
};

export default MissionsTab;