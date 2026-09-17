import React from 'react';

const OverviewTab = ({ selected }) => {
  return (
    <div className="tabContent">
      <p className="mainDesc">{selected.description}</p>
      {selected.structure && (
        <div className="subBlock">
          <h4>Строение и физика</h4>
          <p>{selected.structure}</p>
        </div>
      )}
      {selected.composition && (
        <div className="subBlock">
          <h4>Химический состав</h4>
          <p className="compTag">{selected.composition}</p>
        </div>
      )}
    </div>
  );
};

export default OverviewTab;