'use strict';
module.exports = (sequelize, DataTypes) => {
  const Experiment = sequelize.define('Experiment', {
    website: {
      type: DataTypes.STRING,
      allowNull: false,
    },
    fileURL: {
      type: DataTypes.STRING,
      allowNull: false,
    },
    email: {
      type: DataTypes.STRING,
      allowNull: false,
    },
    ccas: {
      type: DataTypes.ARRAY(DataTypes.ENUM('BBR', 'Cubic', 'Reno')),
      allowNull: false,
    },
    status: {
      type: DataTypes.ENUM('Queued', 'In Progress', 'Completed', 'Failed'),
      allowNull: false,
      defaultValue: 'Queued'
    }
  }, {});

  Experiment.associate = (models) => {
    Experiment.hasMany(models.Flow, {
      foreignKey: 'experimentId',
      as: 'flows',
    });
  };

  return Experiment;
};