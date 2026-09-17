import React from 'react';

const ScaleBadge = ({ simDate }) => {
  const formatted = simDate.toLocaleString('ru-RU');

  return (
    <div className="scaleBadge">
      <span>{formatted}</span>

    </div>
  );
};

export default ScaleBadge;