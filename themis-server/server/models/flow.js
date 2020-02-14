'use strict';
const params = require('../parameters.js');

module.exports = (sequelize, DataTypes) => {
  const Flow = sequelize.define('Flow', {
    btlbw: {
      type: DataTypes.INTEGER,
      allowNull: false,
    },
    rtt: {
      type: DataTypes.INTEGER,
      allowNull: false,
    },
    queueSize: DataTypes.INTEGER,
    cca: DataTypes.ENUM(params.ccas),
    test: DataTypes.ENUM(Object.keys(params.tests)),
    name: DataTypes.STRING,
    status: {
      type: DataTypes.ENUM(
        'Queued for download',
        'Downloading',
        'Queued for analysis',
        'Analyzing data',
        'Completed',
        'Failed download',
        'Failed analysis',
      ),
      allowNull: false,
      defaultValue: 'Queued for download'
    },
    isFinished: {
      type: DataTypes.BOOLEAN,
      allowNull: false,
      defaultValue: false
    },
    results: DataTypes.JSON,
    label: DataTypes.STRING,
  }, {
    setterMethods: {
      status(value) {
        const finishedStatus = ['Completed', 'Failed download', 'Failed analaysis'];
        this.setDataValue('isFinished', finishedStatus.includes(value));
        this.setDataValue('status', value);
      },
    }
  });

  Flow.associate = (models) => {
    Flow.belongsTo(models.Experiment, {
      foreignKey: 'experimentId',
      onDelete: 'CASCADE',
    });
  };

  return Flow;
};
