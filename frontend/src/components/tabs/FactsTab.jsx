import React from 'react';

const FactsTab = ({ facts }) => {
  return (
    <div className="tabContent">
      <ul className="factsList">
        {(facts || []).map((f, i) => <li key={i}>{f}</li>)}
      </ul>
    </div>
  );
};

export default FactsTab;